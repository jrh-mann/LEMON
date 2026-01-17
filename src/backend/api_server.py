"""Flask + Socket.IO API server for the LEMON web app."""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_socketio import SocketIO, emit

from .logging_utils import setup_logging
from .orchestrator import Orchestrator
from .tools import AnalyzeWorkflowTool, ToolRegistry

logger = logging.getLogger("backend.api")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    return Path(__file__).parent.parent.parent


def _decode_data_url(data_url: str) -> tuple[bytes, str]:
    if not data_url.startswith("data:"):
        raise ValueError("Image must be a data URL.")
    header, _, b64 = data_url.partition(",")
    if not b64:
        raise ValueError("Invalid data URL payload.")
    media_type = header.split(";")[0].replace("data:", "")
    ext = "png"
    if media_type == "image/jpeg":
        ext = "jpg"
    elif media_type == "image/webp":
        ext = "webp"
    elif media_type == "image/gif":
        ext = "gif"
    elif media_type == "image/bmp":
        ext = "bmp"
    return base64.b64decode(b64), ext


def _save_uploaded_image(data_url: str) -> str:
    raw, ext = _decode_data_url(data_url)
    uploads_dir = _repo_root() / ".lemon" / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}.{ext}"
    path = uploads_dir / filename
    path.write_bytes(raw)
    # Return repo-relative path for AnalyzeWorkflowTool
    return str(path.relative_to(_repo_root()))


def _extract_tool_calls(response_text: str) -> List[Dict[str, Any]]:
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict) and payload.get("source") == "subagent":
        tool = payload.get("tool") or "unknown"
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        return [{"tool": tool, "arguments": {}, "result": data}]
    return []


def build_orchestrator() -> Orchestrator:
    registry = ToolRegistry()
    registry.register(AnalyzeWorkflowTool(_repo_root()))
    return Orchestrator(registry)


@dataclass
class Conversation:
    id: str
    orchestrator: Orchestrator
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)


class ConversationStore:
    def __init__(self) -> None:
        self._conversations: Dict[str, Conversation] = {}

    def get_or_create(self, conversation_id: Optional[str]) -> Conversation:
        if conversation_id and conversation_id in self._conversations:
            convo = self._conversations[conversation_id]
            convo.updated_at = _utc_now()
            return convo
        new_id = conversation_id or f"conv_{uuid4().hex}"
        convo = Conversation(id=new_id, orchestrator=build_orchestrator())
        self._conversations[new_id] = convo
        return convo

    def get(self, conversation_id: str) -> Optional[Conversation]:
        return self._conversations.get(conversation_id)


conversation_store = ConversationStore()


def create_app() -> Flask:
    setup_logging()
    app = Flask(__name__)
    CORS(app)
    return app


app = create_app()
socketio = SocketIO(app, cors_allowed_origins="*")


@app.get("/api/info")
def api_info() -> Any:
    return jsonify(
        {
            "name": "LEMON Backend",
            "version": "0.1",
            "endpoints": {
                "chat": "/api/chat",
                "workflows": "/api/workflows",
                "search": "/api/search",
            },
        }
    )


@app.post("/api/chat")
def chat() -> Any:
    payload = request.get_json(force=True, silent=True) or {}
    message = payload.get("message", "")
    conversation_id = payload.get("conversation_id")
    image_data = payload.get("image")

    if not isinstance(message, str) or not message.strip():
        return jsonify({"error": "message is required"}), 400

    convo = conversation_store.get_or_create(conversation_id)
    image_name = None
    if isinstance(image_data, str) and image_data.strip():
        try:
            image_name = _save_uploaded_image(image_data)
        except Exception as exc:
            logger.exception("Failed to save uploaded image")
            return jsonify({"error": f"Invalid image data: {exc}"}), 400

    response_text = convo.orchestrator.respond(message, image_name=image_name)
    tool_calls = _extract_tool_calls(response_text)
    convo.updated_at = _utc_now()
    return jsonify(
        {
            "conversation_id": convo.id,
            "response": response_text,
            "tool_calls": tool_calls,
        }
    )


@app.get("/api/chat/<conversation_id>")
def get_conversation(conversation_id: str) -> Any:
    convo = conversation_store.get(conversation_id)
    if not convo:
        return jsonify({"error": "conversation not found"}), 404
    messages = []
    for idx, msg in enumerate(convo.orchestrator.history):
        role = msg.get("role", "assistant")
        content = msg.get("content", "")
        messages.append(
            {
                "id": f"{conversation_id}_{idx}",
                "role": role,
                "content": content,
                "timestamp": _utc_now(),
                "tool_calls": _extract_tool_calls(content),
            }
        )
    return jsonify(
        {
            "id": convo.id,
            "messages": messages,
            "working": {},
            "created_at": convo.created_at,
            "updated_at": convo.updated_at,
        }
    )


@app.get("/api/workflows")
def list_workflows() -> Any:
    return jsonify({"workflows": [], "count": 0})


@app.post("/api/workflows")
def create_workflow() -> Any:
    payload = request.get_json(force=True, silent=True) or {}
    workflow_id = f"wf_{uuid4().hex}"
    name = payload.get("name") or "Untitled Workflow"
    description = payload.get("description") or ""
    response = {
        "workflow_id": workflow_id,
        "name": name,
        "description": description,
        "domain": payload.get("domain"),
        "tags": payload.get("tags") or [],
        "nodes": [],
        "edges": [],
        "message": "Workflow created (placeholder).",
    }
    return jsonify(response)


@app.get("/api/workflows/<workflow_id>")
def get_workflow(workflow_id: str) -> Any:
    return jsonify({"error": "workflow storage not implemented"}), 404


@app.delete("/api/workflows/<workflow_id>")
def delete_workflow(workflow_id: str) -> Any:
    return jsonify({})


@app.get("/api/search")
def search_workflows() -> Any:
    return jsonify({"workflows": []})


@app.get("/api/domains")
def list_domains() -> Any:
    return jsonify({"domains": []})


@app.post("/api/execute/<workflow_id>")
def execute_workflow(workflow_id: str) -> Any:
    return jsonify(
        {
            "success": False,
            "error": "Workflow execution not implemented.",
            "path": [],
            "context": {},
        }
    )


@app.post("/api/validation/start")
def start_validation() -> Any:
    return jsonify({"error": "Validation not implemented."}), 501


@app.post("/api/validation/submit")
def submit_validation() -> Any:
    return jsonify({"error": "Validation not implemented."}), 501


@app.get("/api/validation/<session_id>")
def validation_status(session_id: str) -> Any:
    return jsonify({"error": "Validation not implemented."}), 501


@socketio.on("connect")
def socket_connect() -> None:
    session_id = request.args.get("session_id")
    logger.info("Socket connected session_id=%s sid=%s", session_id, request.sid)


@socketio.on("disconnect")
def socket_disconnect() -> None:
    logger.info("Socket disconnected sid=%s", request.sid)


@socketio.on("chat")
def socket_chat(payload: Dict[str, Any]) -> None:
    session_id = payload.get("session_id")
    conversation_id = payload.get("conversation_id")
    message = payload.get("message", "")
    image_data = payload.get("image")

    if not isinstance(message, str) or not message.strip():
        emit("agent_error", {"task_id": None, "error": "message is required"})
        return

    emit("chat_progress", {"event": "start", "status": "Thinking..."})

    convo = conversation_store.get_or_create(conversation_id)
    image_name = None
    if isinstance(image_data, str) and image_data.strip():
        try:
            image_name = _save_uploaded_image(image_data)
        except Exception as exc:
            logger.exception("Failed to save uploaded image")
            emit("agent_error", {"task_id": None, "error": f"Invalid image: {exc}"})
            return

    response_text = convo.orchestrator.respond(message, image_name=image_name)
    tool_calls = _extract_tool_calls(response_text)
    convo.updated_at = _utc_now()

    emit(
        "chat_response",
        {
            "response": response_text,
            "conversation_id": convo.id,
            "tool_calls": tool_calls,
            "task_id": None,
        },
    )
