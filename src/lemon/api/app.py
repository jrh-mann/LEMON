"""Flask API for LEMON v2.

This provides REST endpoints for:
- Workflow CRUD operations
- Search and discovery
- Workflow execution
- Validation sessions
- Orchestrator chat
"""

import sys
from pathlib import Path

# Add src to path - must come before any lemon imports
src_path = str(Path(__file__).parent.parent.parent)
if src_path not in sys.path:
    sys.path.insert(0, src_path)

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum


def serialize_for_json(obj: Any) -> Any:
    """Recursively convert datetime objects to ISO strings for JSON serialization."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {k: serialize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [serialize_for_json(item) for item in obj]
    return obj

from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room

# Import directly from submodules to avoid lemon/__init__.py conflicts
from lemon.core.blocks import (
    Workflow, WorkflowMetadata, InputBlock, DecisionBlock, OutputBlock,
    Connection, InputType, Range, PortType, WorkflowSummary
)
from lemon.storage.repository import InMemoryWorkflowRepository
from lemon.search.service import SearchService
from lemon.execution.executor import WorkflowExecutor
from lemon.validation.session import ValidationSessionManager
from lemon.validation.case_generator import CaseGenerator
from lemon.agent.tools import create_tool_registry
from lemon.agent.context import ConversationContext, ConversationStore
from lemon.agent.orchestrator import Orchestrator

# Initialize Flask app with SocketIO
template_dir = Path(__file__).parent / "templates"
static_dir = Path(__file__).parent / "static"
app = Flask(__name__, template_folder=str(template_dir), static_folder=str(static_dir))
CORS(app)
# Use threading mode for dev to avoid websocket issues with Werkzeug.
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


# -----------------------------------------------------------------------------
# Background Task Management
# -----------------------------------------------------------------------------

class TaskStatus(Enum):
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class BackgroundTask:
    """A background task (e.g., image analysis) that can ask questions."""
    id: str
    session_id: str  # WebSocket room to push updates to
    status: TaskStatus = TaskStatus.RUNNING
    pending_question: Optional[str] = None
    pending_data: Optional[Dict[str, Any]] = None  # Data extracted so far
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    # Threading event for waiting on user input
    _answer_event: threading.Event = field(default_factory=threading.Event)
    _answer: Optional[str] = None


# Store for background tasks
background_tasks: Dict[str, BackgroundTask] = {}

# Disable caching for development
@app.after_request
def add_no_cache_headers(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# Initialize components
repository = InMemoryWorkflowRepository()
search_service = SearchService(repository)
executor = WorkflowExecutor(repository)
case_generator = CaseGenerator(seed=42)
session_manager = ValidationSessionManager(repository, executor, case_generator)
tool_registry = create_tool_registry(repository, search_service, executor, session_manager)
orchestrator = Orchestrator(tool_registry)
conversation_store = ConversationStore()

# Seed with example workflows
def seed_example_workflows():
    """Add example workflows to the repository.

    All workflows follow a clean hierarchical structure:
    - All inputs feed into the first decision
    - Linear chain: d1 → d2 → d3 (No branch continues down)
    - Yes branches terminate at outputs
    """
    workflows = [
        # Simple 3-tier: eGFR >= 90? → >= 60? → >= 30?
        Workflow(
            id="ckd-staging",
            metadata=WorkflowMetadata(
                name="CKD Staging",
                description="Stage chronic kidney disease based on eGFR values",
                domain="nephrology",
                tags=["ckd", "staging", "egfr", "kidney"],
                validation_score=85.0,
                validation_count=25,
            ),
            blocks=[
                InputBlock(id="egfr", name="eGFR", input_type=InputType.FLOAT,
                          range=Range(min=0, max=200), description="Estimated GFR in mL/min/1.73m²"),
                DecisionBlock(id="d1", condition="eGFR >= 60", description="eGFR >= 60?"),
                DecisionBlock(id="d2", condition="eGFR >= 30", description="eGFR >= 30?"),
                DecisionBlock(id="d3", condition="eGFR >= 15", description="eGFR >= 15?"),
                OutputBlock(id="o1", value="Stage 1-2: Normal/Mild"),
                OutputBlock(id="o2", value="Stage 3: Moderate CKD"),
                OutputBlock(id="o3", value="Stage 4: Severe CKD"),
                OutputBlock(id="o4", value="Stage 5: Kidney Failure"),
            ],
            connections=[
                Connection(from_block="egfr", to_block="d1"),
                Connection(from_block="d1", to_block="o1", from_port=PortType.TRUE),
                Connection(from_block="d1", to_block="d2", from_port=PortType.FALSE),
                Connection(from_block="d2", to_block="o2", from_port=PortType.TRUE),
                Connection(from_block="d2", to_block="d3", from_port=PortType.FALSE),
                Connection(from_block="d3", to_block="o3", from_port=PortType.TRUE),
                Connection(from_block="d3", to_block="o4", from_port=PortType.FALSE),
            ],
        ),
        # Simple 2-tier diabetes check
        Workflow(
            id="diabetes-risk",
            metadata=WorkflowMetadata(
                name="Diabetes Diagnosis",
                description="Diagnose diabetes based on HbA1c",
                domain="endocrinology",
                tags=["diabetes", "hba1c", "diagnosis"],
                validation_score=92.0,
                validation_count=40,
            ),
            blocks=[
                InputBlock(id="hba1c", name="HbA1c", input_type=InputType.FLOAT,
                          range=Range(min=4.0, max=15.0), description="HbA1c percentage"),
                DecisionBlock(id="d1", condition="HbA1c >= 6.5", description="HbA1c >= 6.5%?"),
                DecisionBlock(id="d2", condition="HbA1c >= 5.7", description="HbA1c >= 5.7%?"),
                OutputBlock(id="o1", value="Diabetes"),
                OutputBlock(id="o2", value="Prediabetes"),
                OutputBlock(id="o3", value="Normal"),
            ],
            connections=[
                Connection(from_block="hba1c", to_block="d1"),
                Connection(from_block="d1", to_block="o1", from_port=PortType.TRUE),
                Connection(from_block="d1", to_block="d2", from_port=PortType.FALSE),
                Connection(from_block="d2", to_block="o2", from_port=PortType.TRUE),
                Connection(from_block="d2", to_block="o3", from_port=PortType.FALSE),
            ],
        ),
        # Blood pressure - 3 tier
        Workflow(
            id="bp-classification",
            metadata=WorkflowMetadata(
                name="Blood Pressure Classification",
                description="Classify blood pressure according to AHA guidelines",
                domain="cardiology",
                tags=["blood-pressure", "hypertension", "cardiovascular"],
                validation_score=78.0,
                validation_count=15,
            ),
            blocks=[
                InputBlock(id="systolic", name="systolic_bp", input_type=InputType.INT,
                          range=Range(min=70, max=250), description="Systolic BP mmHg"),
                DecisionBlock(id="d1", condition="systolic_bp >= 180", description="Systolic >= 180?"),
                DecisionBlock(id="d2", condition="systolic_bp >= 140", description="Systolic >= 140?"),
                DecisionBlock(id="d3", condition="systolic_bp >= 120", description="Systolic >= 120?"),
                OutputBlock(id="o1", value="Hypertensive Crisis"),
                OutputBlock(id="o2", value="Hypertension"),
                OutputBlock(id="o3", value="Elevated"),
                OutputBlock(id="o4", value="Normal"),
            ],
            connections=[
                Connection(from_block="systolic", to_block="d1"),
                Connection(from_block="d1", to_block="o1", from_port=PortType.TRUE),
                Connection(from_block="d1", to_block="d2", from_port=PortType.FALSE),
                Connection(from_block="d2", to_block="o2", from_port=PortType.TRUE),
                Connection(from_block="d2", to_block="d3", from_port=PortType.FALSE),
                Connection(from_block="d3", to_block="o3", from_port=PortType.TRUE),
                Connection(from_block="d3", to_block="o4", from_port=PortType.FALSE),
            ],
        ),
        # BMI - 3 tier
        Workflow(
            id="bmi-classification",
            metadata=WorkflowMetadata(
                name="BMI Classification",
                description="Classify BMI into WHO categories",
                domain="general",
                tags=["bmi", "obesity", "weight"],
                validation_score=95.0,
                validation_count=50,
            ),
            blocks=[
                InputBlock(id="bmi", name="BMI", input_type=InputType.FLOAT,
                          range=Range(min=10, max=60), description="Body Mass Index kg/m²"),
                DecisionBlock(id="d1", condition="BMI >= 30", description="BMI >= 30?"),
                DecisionBlock(id="d2", condition="BMI >= 25", description="BMI >= 25?"),
                DecisionBlock(id="d3", condition="BMI >= 18.5", description="BMI >= 18.5?"),
                OutputBlock(id="o1", value="Obese"),
                OutputBlock(id="o2", value="Overweight"),
                OutputBlock(id="o3", value="Normal"),
                OutputBlock(id="o4", value="Underweight"),
            ],
            connections=[
                Connection(from_block="bmi", to_block="d1"),
                Connection(from_block="d1", to_block="o1", from_port=PortType.TRUE),
                Connection(from_block="d1", to_block="d2", from_port=PortType.FALSE),
                Connection(from_block="d2", to_block="o2", from_port=PortType.TRUE),
                Connection(from_block="d2", to_block="d3", from_port=PortType.FALSE),
                Connection(from_block="d3", to_block="o3", from_port=PortType.TRUE),
                Connection(from_block="d3", to_block="o4", from_port=PortType.FALSE),
            ],
        ),
        # Chest pain - 2 tier
        Workflow(
            id="chest-pain-triage",
            metadata=WorkflowMetadata(
                name="Chest Pain Triage",
                description="Triage chest pain by severity",
                domain="emergency",
                tags=["chest-pain", "triage", "cardiac"],
                validation_score=72.0,
                validation_count=18,
            ),
            blocks=[
                InputBlock(id="severity", name="pain_severity", input_type=InputType.INT,
                          range=Range(min=1, max=10), description="Pain severity 1-10"),
                DecisionBlock(id="d1", condition="pain_severity >= 8", description="Severity >= 8?"),
                DecisionBlock(id="d2", condition="pain_severity >= 5", description="Severity >= 5?"),
                OutputBlock(id="o1", value="High Priority - Immediate"),
                OutputBlock(id="o2", value="Medium Priority"),
                OutputBlock(id="o3", value="Low Priority"),
            ],
            connections=[
                Connection(from_block="severity", to_block="d1"),
                Connection(from_block="d1", to_block="o1", from_port=PortType.TRUE),
                Connection(from_block="d1", to_block="d2", from_port=PortType.FALSE),
                Connection(from_block="d2", to_block="o2", from_port=PortType.TRUE),
                Connection(from_block="d2", to_block="o3", from_port=PortType.FALSE),
            ],
        ),
        # Anemia - 2 tier
        Workflow(
            id="anemia-classification",
            metadata=WorkflowMetadata(
                name="Anemia Classification",
                description="Classify anemia severity by hemoglobin",
                domain="hematology",
                tags=["anemia", "hemoglobin", "blood"],
                validation_score=88.0,
                validation_count=32,
            ),
            blocks=[
                InputBlock(id="hgb", name="hemoglobin", input_type=InputType.FLOAT,
                          range=Range(min=3.0, max=20.0), description="Hemoglobin g/dL"),
                DecisionBlock(id="d1", condition="hemoglobin >= 12", description="Hgb >= 12?"),
                DecisionBlock(id="d2", condition="hemoglobin >= 8", description="Hgb >= 8?"),
                OutputBlock(id="o1", value="Normal"),
                OutputBlock(id="o2", value="Mild Anemia"),
                OutputBlock(id="o3", value="Severe Anemia"),
            ],
            connections=[
                Connection(from_block="hgb", to_block="d1"),
                Connection(from_block="d1", to_block="o1", from_port=PortType.TRUE),
                Connection(from_block="d1", to_block="d2", from_port=PortType.FALSE),
                Connection(from_block="d2", to_block="o2", from_port=PortType.TRUE),
                Connection(from_block="d2", to_block="o3", from_port=PortType.FALSE),
            ],
        ),
        # Stroke risk - 2 tier
        Workflow(
            id="stroke-risk-chads",
            metadata=WorkflowMetadata(
                name="Stroke Risk Assessment",
                description="Assess stroke risk by age",
                domain="neurology",
                tags=["stroke", "risk", "age"],
                validation_score=91.0,
                validation_count=45,
            ),
            blocks=[
                InputBlock(id="age", name="age", input_type=InputType.INT,
                          range=Range(min=18, max=120), description="Patient age in years"),
                DecisionBlock(id="d1", condition="age >= 75", description="Age >= 75?"),
                DecisionBlock(id="d2", condition="age >= 65", description="Age >= 65?"),
                OutputBlock(id="o1", value="High Risk"),
                OutputBlock(id="o2", value="Moderate Risk"),
                OutputBlock(id="o3", value="Low Risk"),
            ],
            connections=[
                Connection(from_block="age", to_block="d1"),
                Connection(from_block="d1", to_block="o1", from_port=PortType.TRUE),
                Connection(from_block="d1", to_block="d2", from_port=PortType.FALSE),
                Connection(from_block="d2", to_block="o2", from_port=PortType.TRUE),
                Connection(from_block="d2", to_block="o3", from_port=PortType.FALSE),
            ],
        ),
        # TSH - 2 tier
        Workflow(
            id="thyroid-tsh-interpret",
            metadata=WorkflowMetadata(
                name="TSH Interpretation",
                description="Interpret TSH levels",
                domain="endocrinology",
                tags=["thyroid", "tsh"],
                validation_score=89.0,
                validation_count=28,
            ),
            blocks=[
                InputBlock(id="tsh", name="TSH", input_type=InputType.FLOAT,
                          range=Range(min=0.01, max=100.0), description="TSH level mIU/L"),
                DecisionBlock(id="d1", condition="TSH > 4.0", description="TSH > 4.0?"),
                DecisionBlock(id="d2", condition="TSH < 0.4", description="TSH < 0.4?"),
                OutputBlock(id="o1", value="Hypothyroid"),
                OutputBlock(id="o2", value="Hyperthyroid"),
                OutputBlock(id="o3", value="Normal"),
            ],
            connections=[
                Connection(from_block="tsh", to_block="d1"),
                Connection(from_block="d1", to_block="o1", from_port=PortType.TRUE),
                Connection(from_block="d1", to_block="d2", from_port=PortType.FALSE),
                Connection(from_block="d2", to_block="o2", from_port=PortType.TRUE),
                Connection(from_block="d2", to_block="o3", from_port=PortType.FALSE),
            ],
        ),
    ]

    for wf in workflows:
        repository.save(wf)

seed_example_workflows()


# -----------------------------------------------------------------------------
# Health Check
# -----------------------------------------------------------------------------

@app.route("/")
def index():
    """Serve frontend."""
    return render_template("index.html")


@app.route("/api")
def api_info():
    """API info."""
    return jsonify({
        "name": "LEMON v2 API",
        "version": "2.0.0",
        "endpoints": {
            "workflows": "/api/workflows",
            "search": "/api/search",
            "execute": "/api/execute",
            "validation": "/api/validation",
            "chat": "/api/chat",
        }
    })


@app.route("/api/health")
def health():
    """Health check."""
    return jsonify({"status": "healthy"})


# -----------------------------------------------------------------------------
# Workflow Endpoints
# -----------------------------------------------------------------------------

@app.route("/api/workflows", methods=["GET"])
def list_workflows():
    """List all workflows."""
    workflows = repository.list()
    return jsonify({
        "workflows": [w.model_dump() for w in workflows],
        "count": len(workflows),
    })


@app.route("/api/workflows/<workflow_id>", methods=["GET"])
def get_workflow(workflow_id):
    """Get a specific workflow."""
    workflow = repository.get(workflow_id)
    if workflow is None:
        return jsonify({"error": f"Workflow not found: {workflow_id}"}), 404

    return jsonify(workflow.model_dump())


@app.route("/api/workflows", methods=["POST"])
def create_workflow():
    """Create a new workflow."""
    result = orchestrator.execute_tool("create_workflow", request.json)
    if result.success:
        return jsonify(result.data), 201
    return jsonify({"error": result.error}), 400


@app.route("/api/workflows/<workflow_id>", methods=["DELETE"])
def delete_workflow(workflow_id):
    """Delete a workflow."""
    if repository.delete(workflow_id):
        return jsonify({"deleted": workflow_id})
    return jsonify({"error": "Workflow not found"}), 404


# -----------------------------------------------------------------------------
# Search Endpoints
# -----------------------------------------------------------------------------

@app.route("/api/search", methods=["GET"])
def search_workflows():
    """Search workflows."""
    args = {
        "text": request.args.get("q"),
        "domain": request.args.get("domain"),
        "validated_only": request.args.get("validated") == "true",
        "input_name": request.args.get("input"),
        "output_value": request.args.get("output"),
    }
    # Remove None values
    args = {k: v for k, v in args.items() if v}

    result = orchestrator.execute_tool("search_library", args)
    if result.success:
        return jsonify(result.data)
    return jsonify({"error": result.error}), 400


@app.route("/api/domains", methods=["GET"])
def list_domains():
    """List all domains."""
    result = orchestrator.execute_tool("list_domains", {})
    if result.success:
        return jsonify(result.data)
    return jsonify({"error": result.error}), 400


# -----------------------------------------------------------------------------
# Execution Endpoints
# -----------------------------------------------------------------------------

@app.route("/api/execute/<workflow_id>", methods=["POST"])
def execute_workflow(workflow_id):
    """Execute a workflow."""
    inputs = request.json or {}
    result = orchestrator.execute_tool("execute_workflow", {
        "workflow_id": workflow_id,
        "inputs": inputs,
    })
    if result.success:
        return jsonify(result.data)
    return jsonify({"error": result.error}), 400


# -----------------------------------------------------------------------------
# Validation Endpoints
# -----------------------------------------------------------------------------

@app.route("/api/validation/start", methods=["POST"])
def start_validation():
    """Start a validation session."""
    data = request.json or {}
    result = orchestrator.execute_tool("start_validation", {
        "workflow_id": data.get("workflow_id"),
        "case_count": data.get("case_count", 10),
        "strategy": data.get("strategy", "comprehensive"),
    })
    if result.success:
        return jsonify(result.data)
    return jsonify({"error": result.error}), 400


@app.route("/api/validation/submit", methods=["POST"])
def submit_validation():
    """Submit a validation answer."""
    data = request.json or {}
    result = orchestrator.execute_tool("submit_validation", {
        "session_id": data.get("session_id"),
        "answer": data.get("answer"),
    })
    if result.success:
        return jsonify(result.data)
    return jsonify({"error": result.error}), 400


@app.route("/api/validation/<session_id>", methods=["GET"])
def get_validation_session(session_id):
    """Get validation session status."""
    try:
        session = session_manager.get_session(session_id)
        current_case = session_manager.get_current_case(session_id)
        score = session_manager.get_score(session_id)
        return jsonify({
            "session": session.to_dict(),
            "current_case": current_case.to_dict() if current_case else None,
            "score": score.to_dict(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 404


# -----------------------------------------------------------------------------
# Chat Endpoints
# -----------------------------------------------------------------------------

@app.route("/api/chat", methods=["POST"])
def chat():
    """Chat with the orchestrator."""
    data = request.json or {}
    message = data.get("message", "")
    conversation_id = data.get("conversation_id")
    image = data.get("image")  # Base64 data URL for vision

    # Get or create conversation
    if conversation_id:
        context = conversation_store.get(conversation_id)
        if context is None:
            context = conversation_store.create()
    else:
        context = conversation_store.create()

    # Process message (with optional image for vision)
    response = orchestrator.process_message(context, message, image=image)

    return jsonify({
        "conversation_id": context.id,
        "response": response.message,
        "tool_calls": [
            {
                "tool": tc.tool_name,
                "result": tc.result,
            }
            for tc in response.tool_calls
        ],
    })


@app.route("/api/chat/<conversation_id>", methods=["GET"])
def get_conversation(conversation_id):
    """Get conversation history."""
    context = conversation_store.get(conversation_id)
    if context is None:
        return jsonify({"error": "Conversation not found"}), 404

    return jsonify({
        "id": context.id,
        "messages": [m.to_dict() for m in context.messages],
        "working": context.working.to_dict(),
    })


# -----------------------------------------------------------------------------
# Debug/Test Endpoints
# -----------------------------------------------------------------------------

@app.route("/api/test/parse-image", methods=["POST"])
def test_parse_image():
    """Test endpoint to directly parse a flowchart image without the agent.

    POST with JSON: {"image": "data:image/png;base64,..."}

    Returns the raw parsed flowchart structure that would be sent to frontend.
    Use this to test if the backend vision model is parsing images correctly.
    """
    import json as json_lib

    data = request.json or {}
    image = data.get("image")

    if not image:
        return jsonify({"error": "No image provided. Send {\"image\": \"data:image/...;base64,...\"}"}), 400

    # Simple prompt to extract flowchart as JSON
    parse_prompt = """Analyze this flowchart image and extract its structure as JSON.

IMPORTANT: Read the ACTUAL TEXT visible in each box/shape in the image. Do NOT make up labels or use IDs.

Return a JSON object with this exact structure:
{
  "nodes": [
    {"id": "n1", "type": "start|process|decision|end", "label": "THE ACTUAL TEXT FROM THE IMAGE"},
    ...
  ],
  "edges": [
    {"from": "n1", "to": "n2", "label": "optional edge label like Yes/No"},
    ...
  ]
}

Node types:
- "start" = rounded rectangle at the beginning (inputs)
- "decision" = diamond shape (conditions/questions)
- "process" = rectangle (actions/steps)
- "end" = rounded rectangle at the end (outputs/results)

The "label" field MUST contain the human-readable text you see in the image, not IDs or JSON.

Return ONLY the JSON, no other text."""

    try:
        messages = [
            {"role": "user", "content": [
                {"type": "text", "text": parse_prompt},
                {"type": "image_url", "image_url": {"url": image}},
            ]}
        ]

        response = orchestrator._call_azure_openai(messages, [])
        content = response["choices"][0]["message"]["content"]

        # Try to parse the JSON from the response
        # Handle markdown code blocks if present
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        try:
            parsed = json_lib.loads(content)
            return jsonify({
                "success": True,
                "raw_response": response["choices"][0]["message"]["content"],
                "parsed_flowchart": parsed,
            })
        except json_lib.JSONDecodeError as e:
            return jsonify({
                "success": False,
                "error": f"Failed to parse JSON: {str(e)}",
                "raw_response": content,
            })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
        }), 500


@app.route("/test/image-parser")
def test_image_parser_page():
    """Simple HTML page to test image parsing."""
    return """
<!DOCTYPE html>
<html>
<head>
    <title>LEMON - Image Parser Test</title>
    <style>
        body { font-family: system-ui, sans-serif; max-width: 1200px; margin: 40px auto; padding: 20px; }
        h1 { color: #1f6e68; }
        h3 { margin-top: 24px; margin-bottom: 12px; }
        .dropzone { border: 2px dashed #ccc; padding: 40px; text-align: center; margin: 20px 0; border-radius: 8px; }
        .dropzone.dragover { border-color: #1f6e68; background: #f0f9f8; }
        button { background: #1f6e68; color: white; border: none; padding: 12px 24px; border-radius: 6px; cursor: pointer; font-size: 16px; }
        button:disabled { background: #ccc; }
        pre { background: #f5f5f5; padding: 16px; overflow: auto; border-radius: 8px; max-height: 300px; font-size: 12px; }
        .preview { max-width: 400px; margin: 20px 0; }
        .preview img { max-width: 100%; border: 1px solid #ddd; border-radius: 8px; }
        .status { padding: 12px; margin: 12px 0; border-radius: 6px; }
        .status.loading { background: #fff3cd; }
        .status.success { background: #d4edda; }
        .status.error { background: #f8d7da; }
        .comparison { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-top: 24px; }
        .comparison > div { border: 1px solid #ddd; border-radius: 8px; padding: 16px; background: white; }
        .svg-container { background: #fafafa; border-radius: 8px; overflow: hidden; }
        .svg-container svg { width: 100%; height: 400px; }
        .node-list { display: flex; flex-wrap: wrap; gap: 8px; }
        .node-chip { padding: 6px 12px; border-radius: 4px; font-size: 13px; }
        .node-chip.start { background: rgba(31, 110, 104, 0.15); border: 1px solid #1f6e68; }
        .node-chip.decision { background: rgba(201, 138, 44, 0.15); border: 1px solid #c98a2c; }
        .node-chip.process { background: #f0f0f0; border: 1px solid #999; }
        .node-chip.end { background: rgba(62, 124, 77, 0.15); border: 1px solid #3e7c4d; }
        details { margin-top: 16px; }
        summary { cursor: pointer; font-weight: 500; padding: 8px; background: #f5f5f5; border-radius: 4px; }
    </style>
</head>
<body>
    <h1>Image Parser Test</h1>
    <p>Upload a flowchart image to test if the backend parses it correctly. The rendered graph shows exactly what the frontend would display.</p>

    <div class="dropzone" id="dropzone">
        <p>Drag & drop an image here, or click to select</p>
        <input type="file" id="fileInput" accept="image/*" style="display:none">
    </div>

    <div class="preview" id="preview" style="display:none">
        <h3>Uploaded Image:</h3>
        <img id="previewImg">
    </div>

    <button id="parseBtn" disabled>Parse Image</button>

    <div id="status" class="status" style="display:none"></div>

    <div id="result" style="display:none">
        <div class="comparison">
            <div>
                <h3 style="margin-top:0">Original Image</h3>
                <img id="originalImg" style="max-width:100%; border-radius:8px;">
            </div>
            <div>
                <h3 style="margin-top:0">Rendered from Parsed JSON</h3>
                <div class="svg-container" id="svgContainer"></div>
            </div>
        </div>

        <h3>Extracted Nodes</h3>
        <div class="node-list" id="nodeList"></div>

        <details>
            <summary>Raw LLM Response</summary>
            <pre id="rawResponse"></pre>
        </details>

        <details>
            <summary>Parsed JSON</summary>
            <pre id="parsedJson"></pre>
        </details>
    </div>

    <script>
        let imageData = null;
        const dropzone = document.getElementById('dropzone');
        const fileInput = document.getElementById('fileInput');
        const preview = document.getElementById('preview');
        const previewImg = document.getElementById('previewImg');
        const parseBtn = document.getElementById('parseBtn');
        const status = document.getElementById('status');
        const result = document.getElementById('result');

        dropzone.onclick = () => fileInput.click();
        dropzone.ondragover = (e) => { e.preventDefault(); dropzone.classList.add('dragover'); };
        dropzone.ondragleave = () => dropzone.classList.remove('dragover');
        dropzone.ondrop = (e) => {
            e.preventDefault();
            dropzone.classList.remove('dragover');
            handleFile(e.dataTransfer.files[0]);
        };
        fileInput.onchange = (e) => handleFile(e.target.files[0]);

        function handleFile(file) {
            if (!file || !file.type.startsWith('image/')) return;
            const reader = new FileReader();
            reader.onload = (e) => {
                imageData = e.target.result;
                previewImg.src = imageData;
                preview.style.display = 'block';
                parseBtn.disabled = false;
                result.style.display = 'none';
            };
            reader.readAsDataURL(file);
        }

        // Render flowchart as SVG
        function renderFlowchart(flowchart) {
            const nodes = flowchart.nodes || [];
            const edges = flowchart.edges || [];

            // Auto-layout if no positions
            const hasPositions = nodes.some(n => n.x && n.y);
            if (!hasPositions) {
                // Simple vertical layout
                nodes.forEach((n, i) => {
                    n.x = 300;
                    n.y = 80 + i * 120;
                });
            }

            // Calculate bounds
            let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            nodes.forEach(n => {
                minX = Math.min(minX, n.x - 80);
                minY = Math.min(minY, n.y - 40);
                maxX = Math.max(maxX, n.x + 80);
                maxY = Math.max(maxY, n.y + 40);
            });
            const padding = 40;
            const viewBox = `${minX - padding} ${minY - padding} ${maxX - minX + padding * 2} ${maxY - minY + padding * 2}`;

            // Node sizes
            const getSize = (type) => {
                if (type === 'decision') return { w: 120, h: 80 };
                return { w: 140, h: 50 };
            };

            // Colors
            const getColors = (type) => {
                switch(type) {
                    case 'start': return { fill: 'rgba(31, 110, 104, 0.15)', stroke: '#1f6e68' };
                    case 'decision': return { fill: 'rgba(201, 138, 44, 0.15)', stroke: '#c98a2c' };
                    case 'end': return { fill: 'rgba(62, 124, 77, 0.15)', stroke: '#3e7c4d' };
                    default: return { fill: '#f5f5f5', stroke: '#666' };
                }
            };

            // Build node lookup
            const nodeMap = {};
            nodes.forEach(n => nodeMap[n.id] = n);

            // Render edges
            let edgeSvg = '';
            edges.forEach(e => {
                const from = nodeMap[e.from];
                const to = nodeMap[e.to];
                if (!from || !to) return;

                const fromSize = getSize(from.type);
                const toSize = getSize(to.type);

                // Simple straight line from bottom of source to top of target
                const x1 = from.x;
                const y1 = from.y + fromSize.h / 2;
                const x2 = to.x;
                const y2 = to.y - toSize.h / 2;

                edgeSvg += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#333" stroke-width="1.5" marker-end="url(#arrow)"/>`;

                // Edge label
                if (e.label) {
                    const midX = (x1 + x2) / 2;
                    const midY = (y1 + y2) / 2;
                    edgeSvg += `<text x="${midX + 10}" y="${midY}" font-size="11" fill="#666">${e.label}</text>`;
                }
            });

            // Render nodes
            let nodeSvg = '';
            nodes.forEach(n => {
                const size = getSize(n.type);
                const colors = getColors(n.type);
                const x = n.x;
                const y = n.y;

                if (n.type === 'decision') {
                    // Diamond shape
                    const hw = size.w / 2;
                    const hh = size.h / 2;
                    nodeSvg += `<polygon points="${x},${y - hh} ${x + hw},${y} ${x},${y + hh} ${x - hw},${y}" fill="${colors.fill}" stroke="${colors.stroke}" stroke-width="1.5"/>`;
                } else {
                    // Rounded rectangle
                    const rx = (n.type === 'start' || n.type === 'end') ? 25 : 6;
                    nodeSvg += `<rect x="${x - size.w / 2}" y="${y - size.h / 2}" width="${size.w}" height="${size.h}" rx="${rx}" fill="${colors.fill}" stroke="${colors.stroke}" stroke-width="1.5"/>`;
                }

                // Label (truncate if too long)
                let label = n.label || n.id;
                if (label.length > 20) label = label.slice(0, 18) + '...';
                nodeSvg += `<text x="${x}" y="${y + 4}" text-anchor="middle" font-size="12" fill="#333">${label}</text>`;
            });

            return `
                <svg viewBox="${viewBox}" xmlns="http://www.w3.org/2000/svg">
                    <defs>
                        <marker id="arrow" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                            <polygon points="0 0, 10 3.5, 0 7" fill="#333"/>
                        </marker>
                    </defs>
                    <rect width="100%" height="100%" fill="#fafafa"/>
                    ${edgeSvg}
                    ${nodeSvg}
                </svg>
            `;
        }

        parseBtn.onclick = async () => {
            if (!imageData) return;

            parseBtn.disabled = true;
            status.style.display = 'block';
            status.className = 'status loading';
            status.textContent = 'Parsing image... (this may take 10-30 seconds)';
            result.style.display = 'none';

            try {
                const res = await fetch('/api/test/parse-image', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ image: imageData })
                });
                const data = await res.json();

                if (data.success) {
                    status.className = 'status success';
                    status.textContent = 'Parsed successfully!';

                    // Show original image
                    document.getElementById('originalImg').src = imageData;

                    // Render flowchart
                    document.getElementById('svgContainer').innerHTML = renderFlowchart(data.parsed_flowchart);

                    // Show node labels
                    const nodeList = document.getElementById('nodeList');
                    nodeList.innerHTML = (data.parsed_flowchart.nodes || []).map(n =>
                        `<div class="node-chip ${n.type}"><strong>${n.id}:</strong> ${n.label}</div>`
                    ).join('');

                    // Show raw data
                    document.getElementById('rawResponse').textContent = data.raw_response;
                    document.getElementById('parsedJson').textContent = JSON.stringify(data.parsed_flowchart, null, 2);

                    result.style.display = 'block';
                } else {
                    status.className = 'status error';
                    status.textContent = 'Error: ' + data.error;
                    document.getElementById('rawResponse').textContent = data.raw_response || 'No response';
                    document.getElementById('parsedJson').textContent = 'Failed to parse';
                    result.style.display = 'block';
                }
            } catch (err) {
                status.className = 'status error';
                status.textContent = 'Request failed: ' + err.message;
            }

            parseBtn.disabled = false;
        };
    </script>
</body>
</html>
"""


# -----------------------------------------------------------------------------
# WebSocket Events
# -----------------------------------------------------------------------------

@socketio.on('connect')
def handle_connect():
    """Client connected."""
    session_id = request.args.get('session_id', str(uuid.uuid4()))
    join_room(session_id)
    emit('connected', {'session_id': session_id})


@socketio.on('chat')
def handle_chat(data):
    """Handle chat message via WebSocket."""
    session_id = data.get('session_id', 'default')
    message = data.get('message', '')
    conversation_id = data.get('conversation_id')
    image = data.get('image')
    current_workflow_id = data.get('current_workflow_id')  # For editing context

    # Check if this is an answer to a pending question
    for task_id, task in background_tasks.items():
        if task.session_id == session_id and task.status == TaskStatus.WAITING_INPUT:
            # This is an answer to the pending question
            task._answer = message
            task._answer_event.set()
            emit('chat_response', {
                'response': f"Got it, continuing analysis...",
                'conversation_id': conversation_id,
            })
            return

    # Normal chat - process synchronously (image is passed to orchestrator for analysis)
    if conversation_id:
        context = conversation_store.get(conversation_id)
        if context is None:
            context = conversation_store.create()
    else:
        context = conversation_store.create()

    # Progress callback to emit status updates
    def on_progress(event_type: str, data: dict):
        print(f"[DEBUG] on_progress: {event_type} - {data}")
        emit('chat_progress', {
            'event': event_type,
            **data,
        }, room=session_id)
        print(f"[DEBUG] Emitted chat_progress to room {session_id}")

    response = orchestrator.process_message(
        context, message, image=image,
        current_workflow_id=current_workflow_id,
        on_progress=on_progress
    )

    # Check for workflow modification tools and emit events
    workflow_edit_tools = {
        'add_block', 'update_block', 'delete_block',
        'connect_blocks', 'disconnect_blocks', 'create_workflow'
    }

    for tc in response.tool_calls:
        # Only emit for successful tool calls (no 'error' key in result)
        if tc.tool_name in workflow_edit_tools and 'error' not in tc.result:
            # Emit workflow modification event for real-time canvas updates
            emit('workflow_modified', {
                'action': tc.tool_name,
                'data': serialize_for_json(tc.result),
            }, room=session_id)

    emit('chat_response', {
        'conversation_id': context.id,
        'response': response.message,
        'tool_calls': [
            {'tool': tc.tool_name, 'result': serialize_for_json(tc.result)}
            for tc in response.tool_calls
        ],
    })


def run_background_analysis(task: BackgroundTask, context: ConversationContext, message: str, image: str):
    """Run image analysis in background thread with confirmation flow."""
    try:
        # Phase 1: Extract inputs/outputs
        context.add_user_message(message)

        extract_prompt = """Analyze this flowchart image. Extract ONLY the inputs and outputs - do NOT create a workflow yet.

List what you find in this exact format:

### Inputs Found
| Name | Type | Description |
|------|------|-------------|
| ... | ... | ... |

### Outputs Found
- **Output 1** - Description
- **Output 2** - Description

After listing, ask: "Is this correct? Reply 'yes' to continue, or tell me what to change."
"""
        # Call the LLM for extraction
        messages = [
            {"role": "system", "content": orchestrator.get_system_prompt()},
            {"role": "user", "content": [
                {"type": "text", "text": extract_prompt},
                {"type": "image_url", "image_url": {"url": image}},
            ]}
        ]

        response = orchestrator._call_azure_openai(messages, [])
        extraction_text = response["choices"][0]["message"]["content"]

        # Store extraction and ask for confirmation
        task.pending_data = {"extraction": extraction_text, "image": image}
        task.status = TaskStatus.WAITING_INPUT
        task.pending_question = extraction_text

        # Push question to frontend
        socketio.emit('agent_question', {
            'task_id': task.id,
            'question': extraction_text,
        }, room=task.session_id)

        # Wait for user response (timeout after 10 minutes)
        got_answer = task._answer_event.wait(timeout=600)

        if not got_answer:
            task.status = TaskStatus.ERROR
            task.error = "Timed out waiting for confirmation"
            socketio.emit('agent_error', {
                'task_id': task.id,
                'error': task.error,
            }, room=task.session_id)
            return

        # Phase 2: Build workflow based on user's answer
        user_answer = task._answer
        task.status = TaskStatus.RUNNING
        task._answer_event.clear()

        # Add the exchange to context
        context.add_assistant_message(extraction_text, [])
        context.add_user_message(user_answer)

        # Now call the LLM to build the workflow
        build_messages = [
            {"role": "system", "content": orchestrator.get_system_prompt()},
            {"role": "user", "content": [
                {"type": "text", "text": message},
                {"type": "image_url", "image_url": {"url": image}},
            ]},
            {"role": "assistant", "content": extraction_text},
            {"role": "user", "content": user_answer},
        ]

        # Include tools for create_workflow
        tools = orchestrator._build_openai_tools()
        response = orchestrator._call_azure_openai(build_messages, tools)
        result_message = response["choices"][0]["message"]

        # Handle tool calls if the model wants to create a workflow
        while result_message.get("tool_calls"):
            build_messages.append(result_message)

            for tc in result_message["tool_calls"]:
                func = tc["function"]
                tool_name = func["name"]
                try:
                    import json
                    arguments = json.loads(func["arguments"])
                except:
                    arguments = {}

                # Execute the tool
                result = orchestrator.execute_tool(tool_name, arguments)

                build_messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(result.data if result.success else {"error": result.error}),
                })

                # If workflow was created, store result
                if tool_name == "create_workflow" and result.success:
                    task.result = result.data

            # Continue conversation
            response = orchestrator._call_azure_openai(build_messages, tools)
            result_message = response["choices"][0]["message"]

        final_text = result_message.get("content", "")
        task.status = TaskStatus.COMPLETE

        # Push completion to frontend
        socketio.emit('agent_complete', {
            'task_id': task.id,
            'message': final_text,
            'result': task.result,
        }, room=task.session_id)

    except Exception as e:
        task.status = TaskStatus.ERROR
        task.error = str(e)
        socketio.emit('agent_error', {
            'task_id': task.id,
            'error': str(e),
        }, room=task.session_id)


# -----------------------------------------------------------------------------
# Run Server
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("LEMON v2 API Server")
    print("=" * 60)
    print(f"\nServer running at: http://localhost:5001")
    print(f"\nEndpoints:")
    print(f"  GET  /                     - API info")
    print(f"  GET  /api/health           - Health check")
    print(f"  GET  /api/workflows        - List workflows")
    print(f"  GET  /api/workflows/<id>   - Get workflow")
    print(f"  POST /api/workflows        - Create workflow")
    print(f"  GET  /api/search?q=...     - Search workflows")
    print(f"  GET  /api/domains          - List domains")
    print(f"  POST /api/execute/<id>     - Execute workflow")
    print(f"  POST /api/validation/start - Start validation")
    print(f"  POST /api/validation/submit - Submit answer")
    print(f"  POST /api/chat             - Chat with orchestrator")
    print("=" * 60 + "\n")

    socketio.run(app, debug=True, port=5001, allow_unsafe_werkzeug=True)
