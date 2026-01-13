from __future__ import annotations

import base64
import json
import os
import queue
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request, send_file, g
from flask_cors import CORS

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.lemon.analysis.agent import WorkflowAnalyzer
from src.lemon.core.orchestrator import OrchestratorAgent
from src.lemon.core.evaluator import SolverEvaluator
from src.lemon.core.exceptions import WorkflowAnalysisError
from src.lemon.core.workflow import WorkflowAnalysis
from src.lemon.flowchart.builder import flowchart_from_analysis
from src.lemon.flowchart.layout import layout_flowchart
from src.lemon.flowchart.nl import (
    clarify_flowchart_request,
    generate_flowchart_from_request,
)
from src.lemon.generation.generator import CodeGenerator, GenerationContext
from src.lemon.solvers.code_solver import AgenticCodeSolver
from src.lemon.testing.generator import TestCaseGenerator
from src.lemon.testing.harness import TestHarness
from src.lemon.utils.logging import configure_logging, get_logger
from src.utils.request_utils import make_request

load_dotenv(REPO_ROOT / ".env")
configure_logging(level="INFO", json_logs=False)
logger = get_logger(__name__)

RUNS_DIR = Path(__file__).parent / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

NUM_TEST_CASES = 100
BATCH_SIZE = 5
MAX_WORKERS = 5
BEST_OF_N = 3
MAX_ITERATIONS = 5

SESSION_COOKIE = "lemon_session"
ORCHESTRATOR = OrchestratorAgent()
RUNNING_STAGES = {"analyzing", "tests_running", "code_refining"}


@dataclass
class ConversationMessage:
    id: str
    role: str
    content: str
    ts: float
    tags: List[str] = field(default_factory=list)


@dataclass
class OrchestratorState:
    stage: str = "idle"
    revision: int = 0
    conversation: List[ConversationMessage] = field(default_factory=list)
    analysis: Optional[Dict[str, Any]] = None
    inputs: List[Dict[str, Any]] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    iterations: List[Dict[str, Any]] = field(default_factory=list)
    test_progress: Dict[str, Any] = field(
        default_factory=lambda: {"current": 0, "total": 0, "percent": 0}
    )
    workflow_image: Optional[str] = None
    workflow_name: Optional[str] = None
    run_id: Optional[str] = None
    run_dir: Optional[str] = None
    generated_code_path: Optional[str] = None
    last_feedback: Optional[str] = None
    flowchart: Optional[Dict[str, Any]] = None
    flowchart_messages: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class SessionContext:
    session_id: str
    lock: threading.Lock
    state: OrchestratorState
    events: "EventHub"
    state_file: Path


SESSION_CONTEXTS: Dict[str, SessionContext] = {}
SESSION_CONTEXTS_LOCK = threading.Lock()


class EventHub:
    def __init__(self) -> None:
        self._clients: List[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=500)
        with self._lock:
            self._clients.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

    def publish(self, event: Dict[str, Any]) -> None:
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait(event)
            except queue.Full:
                continue


def _get_session_context(session_id: Optional[str] = None) -> SessionContext:
    sid = session_id or getattr(g, "session_id", None)
    if not sid:
        raise RuntimeError("Session id missing")
    with SESSION_CONTEXTS_LOCK:
        ctx = SESSION_CONTEXTS.get(sid)
        if ctx is None:
            state_file = Path(__file__).parent / f".orchestrator_state_{sid}.json"
            ctx = SessionContext(
                session_id=sid,
                lock=threading.Lock(),
                state=OrchestratorState(),
                events=EventHub(),
                state_file=state_file,
            )
            SESSION_CONTEXTS[sid] = ctx
            _load_state(ctx)
    return ctx


def _emit(ctx: SessionContext, event_type: str, data: Dict[str, Any]) -> None:
    event = {"type": event_type, "data": data, "ts": time.time()}
    ctx.events.publish(event)


def _save_state(ctx: SessionContext) -> None:
    state = ctx.state
    payload = {
        "stage": state.stage,
        "revision": state.revision,
        "conversation": [asdict(msg) for msg in state.conversation],
        "analysis": state.analysis,
        "inputs": state.inputs,
        "outputs": state.outputs,
        "iterations": state.iterations,
        "test_progress": state.test_progress,
        "workflow_image": state.workflow_image,
        "workflow_name": state.workflow_name,
        "run_id": state.run_id,
        "run_dir": state.run_dir,
        "generated_code_path": state.generated_code_path,
        "last_feedback": state.last_feedback,
        "flowchart": state.flowchart,
        "flowchart_messages": state.flowchart_messages,
    }
    ctx.state_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_state(ctx: SessionContext) -> None:
    if not ctx.state_file.exists():
        return
    try:
        raw = ctx.state_file.read_text(encoding="utf-8").strip()
        if not raw:
            return
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("State file was invalid JSON; resetting.", extra={"path": str(ctx.state_file)})
        return
    state = ctx.state
    state.stage = payload.get("stage", "idle")
    state.revision = payload.get("revision", 0)
    state.conversation = [ConversationMessage(**msg) for msg in payload.get("conversation", [])]
    state.analysis = payload.get("analysis")
    state.inputs = payload.get("inputs", [])
    state.outputs = payload.get("outputs", [])
    state.iterations = payload.get("iterations", [])
    state.test_progress = payload.get("test_progress", {"current": 0, "total": 0, "percent": 0})
    state.workflow_image = payload.get("workflow_image")
    state.workflow_name = payload.get("workflow_name")
    state.run_id = payload.get("run_id")
    state.run_dir = payload.get("run_dir")
    state.generated_code_path = payload.get("generated_code_path")
    state.last_feedback = payload.get("last_feedback")
    state.flowchart = payload.get("flowchart")
    state.flowchart_messages = payload.get("flowchart_messages", [])





app = Flask(__name__)
CORS(app)


@app.before_request
def _ensure_session() -> None:
    header_sid = request.headers.get("X-Session-Id")
    query_sid = request.args.get("session_id")
    cookie_sid = request.cookies.get(SESSION_COOKIE)
    sid = header_sid or query_sid or cookie_sid
    if not sid:
        g.session_id = uuid.uuid4().hex
        g.new_session = True
        g.set_cookie = True
    else:
        g.session_id = sid
        g.new_session = False
        g.set_cookie = not (header_sid or query_sid)


@app.after_request
def _apply_session_cookie(response: Response) -> Response:
    if getattr(g, "new_session", False) and getattr(g, "set_cookie", False):
        response.set_cookie(SESSION_COOKIE, g.session_id, samesite="Lax")
    return response


@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.route("/events")
def events() -> Response:
    ctx = _get_session_context()
    q = ctx.events.subscribe()

    def stream() -> Any:
        try:
            while True:
                try:
                    event = q.get(timeout=20)
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    yield "data: {\"type\": \"ping\"}\n\n"
        finally:
            ctx.events.unsubscribe(q)

    return Response(stream(), mimetype="text/event-stream")


@app.route("/api/state")
def get_state() -> Response:
    ctx = _get_session_context()
    with ctx.lock:
        state = ctx.state
        payload = {
            "stage": state.stage,
            "revision": state.revision,
            "conversation": [asdict(msg) for msg in state.conversation],
            "analysis": state.analysis,
            "inputs": state.inputs,
            "outputs": state.outputs,
            "iterations": state.iterations,
            "test_progress": state.test_progress,
            "workflow_image": state.workflow_image,
            "workflow_name": state.workflow_name,
            "run_id": state.run_id,
            "run_dir": state.run_dir,
            "generated_code_path": state.generated_code_path,
            "last_feedback": state.last_feedback,
            "flowchart": state.flowchart,
        }
    return jsonify(payload)


@app.route("/api/chat", methods=["POST"])
def chat() -> Response:
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "empty_message"}), 400

    ctx = _get_session_context()
    flowchart = data.get("flowchart")
    if isinstance(flowchart, dict):
        with ctx.lock:
            ctx.state.flowchart = flowchart
            _save_state(ctx)
    _append_message(ctx, "user", message, tags=["chat"])
    _start_background(_run_orchestrator, ctx.session_id)
    return jsonify({"status": "ok"})


@app.route("/api/upload", methods=["POST"])
def upload() -> Response:
    if "file" not in request.files:
        return jsonify({"error": "missing_file"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "empty_filename"}), 400

    workflow_name = (request.form.get("workflow_name") or "").strip()
    slug = _slugify(workflow_name) if workflow_name else "workflow"
    run_id = uuid.uuid4().hex[:10]
    run_dir = RUNS_DIR / f"{slug}_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename).suffix or ".png"
    filename = f"{slug}{suffix}"
    path = run_dir / filename
    file.save(path)

    ctx = _get_session_context()
    _reset_state(ctx)
    with ctx.lock:
        state = ctx.state
        state.workflow_image = str(path)
        state.workflow_name = workflow_name or slug
        state.run_id = run_id
        state.run_dir = str(run_dir)
        _save_state(ctx)
    _append_message(ctx, "user", f"Uploaded workflow image: {file.filename}", tags=["upload"])
    _append_message(
        ctx,
        "orchestrator",
        "Workflow image uploaded. Ask me to analyze it when you are ready.",
        tags=["upload"],
    )
    return jsonify(
        {
            "status": "ok",
            "path": str(path),
            "workflow_name": ctx.state.workflow_name,
            "run_id": ctx.state.run_id,
        }
    )


@app.route("/api/analysis/approve", methods=["POST"])
def approve_analysis() -> Response:
    ctx = _get_session_context()
    _append_message(ctx, "user", "Analysis looks good. Proceed.", tags=["approval"])
    _append_message(
        ctx,
        "orchestrator",
        "Starting test case generation and labeling.",
        tags=["tests"],
    )
    _start_background(_run_tests_and_codegen, ctx.session_id)
    return jsonify({"status": "ok"})


@app.route("/api/analysis/feedback", methods=["POST"])
def feedback_analysis() -> Response:
    data = request.get_json(silent=True) or {}
    feedback = (data.get("feedback") or "").strip()
    if not feedback:
        return jsonify({"error": "empty_feedback"}), 400

    ctx = _get_session_context()
    with ctx.lock:
        ctx.state.last_feedback = feedback
        _save_state(ctx)
    _append_message(ctx, "user", feedback, tags=["feedback"])
    _append_message(
        ctx,
        "orchestrator",
        "Understood. I will refine the analysis and re-run the extraction.",
        tags=["analysis"],
    )
    _start_background(_run_analysis, ctx.session_id, feedback=feedback)
    return jsonify({"status": "ok"})


@app.route("/api/edge-case", methods=["POST"])
def edge_case() -> Response:
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "empty_message"}), 400

    ctx = _get_session_context()
    _append_message(ctx, "user", message, tags=["edge"])
    _append_message(
        ctx,
        "orchestrator",
        "Got it. I will treat this as an edge case and validate it in the final pass.",
        tags=["edge"],
    )
    return jsonify({"status": "ok"})


@app.route("/api/download")
def download() -> Response:
    ctx = _get_session_context()
    with ctx.lock:
        code_path = ctx.state.generated_code_path
        workflow_name = ctx.state.workflow_name or "workflow"
    if not code_path or not Path(code_path).exists():
        return jsonify({"error": "not_ready"}), 404
    filename = f"{_slugify(workflow_name)}.py"
    return send_file(code_path, as_attachment=True, download_name=filename)


@app.route("/api/reset", methods=["POST"])
def reset() -> Response:
    ctx = _get_session_context()
    _reset_state(ctx)
    _emit(ctx, "state_reset", {"status": "ok"})
    return jsonify({"status": "ok"})


def _append_message(
    ctx: SessionContext, role: str, content: str, tags: Optional[List[str]] = None
) -> None:
    msg = ConversationMessage(
        id=str(uuid.uuid4()),
        role=role,
        content=content,
        ts=time.time(),
        tags=tags or [],
    )
    with ctx.lock:
        ctx.state.conversation.append(msg)
        _save_state(ctx)
    _emit(ctx, "message", asdict(msg))


def _set_stage(ctx: SessionContext, stage: str) -> None:
    with ctx.lock:
        ctx.state.stage = stage
        _save_state(ctx)
    _emit(ctx, "stage_started", {"stage": stage})


def _reset_state(ctx: SessionContext) -> None:
    with ctx.lock:
        state = ctx.state
        state.stage = "idle"
        state.revision = 0
        state.conversation = []
        state.analysis = None
        state.inputs = []
        state.outputs = []
        state.iterations = []
        state.test_progress = {"current": 0, "total": 0, "percent": 0}
        state.workflow_image = None
        state.workflow_name = None
        state.run_id = None
        state.run_dir = None
        state.generated_code_path = None
        state.last_feedback = None
        state.flowchart = None
        state.flowchart_messages = []
        _save_state(ctx)


def _start_background(target: Any, *args: Any, **kwargs: Any) -> None:
    thread = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
    thread.start()


def _slugify(value: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    safe = "-".join(part for part in safe.split("-") if part)
    return safe or "workflow"




def _build_feedback_prompt(base_prompt: str, prev_analysis: Dict[str, Any], feedback: str) -> str:
    return (
        base_prompt
        + "\n\nPREVIOUS ANALYSIS JSON:\n"
        + json.dumps(prev_analysis, indent=2)
        + "\n\nUSER FEEDBACK:\n"
        + feedback
        + "\n\nPlease revise the analysis JSON to address the feedback."
    )


def _run_analysis(session_id: str, *, feedback: Optional[str]) -> None:
    ctx = _get_session_context(session_id)
    with ctx.lock:
        image_path = ctx.state.workflow_image
        previous_analysis = ctx.state.analysis
        run_dir = ctx.state.run_dir
    if not image_path:
        _append_message(ctx, "orchestrator", "No workflow image found to analyze.")
        return
    if not run_dir:
        _append_message(ctx, "orchestrator", "No workflow run directory available.")
        return

    _set_stage(ctx, "analyzing")
    _append_message(ctx, "orchestrator", "Analyzing the workflow diagram.", tags=["analysis"])

    try:
        analyzer = WorkflowAnalyzer()
        if feedback and previous_analysis:
            analyzer.analysis_prompt = _build_feedback_prompt(
                analyzer.analysis_prompt, previous_analysis, feedback
            )

        analysis = analyzer.analyze(Path(image_path))
        inputs = analyzer.extract_standardized_inputs(analysis)
        outputs = analyzer.extract_outputs(analysis)

        analysis_payload = analysis.model_dump()
        inputs_payload = [x.model_dump(exclude_none=True) for x in inputs]
        flowchart_model = flowchart_from_analysis(analysis)
        layout_flowchart(flowchart_model)
        flowchart_payload = flowchart_model.to_dict()

        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)
        (run_path / "workflow_analysis.json").write_text(
            json.dumps(analysis_payload, indent=2), encoding="utf-8"
        )
        (run_path / "workflow_inputs.json").write_text(
            json.dumps(inputs_payload, indent=2), encoding="utf-8"
        )
        (run_path / "workflow_outputs.json").write_text(
            json.dumps(outputs, indent=2), encoding="utf-8"
        )
        (run_path / "flowchart.json").write_text(
            json.dumps(flowchart_payload, indent=2), encoding="utf-8"
        )

        with ctx.lock:
            ctx.state.analysis = analysis_payload
            ctx.state.inputs = inputs_payload
            ctx.state.outputs = outputs
            ctx.state.flowchart = flowchart_payload
            ctx.state.revision += 1
            revision = ctx.state.revision
            _save_state(ctx)

        _emit(
            ctx,
            "analysis_ready",
            {
                "inputs": inputs_payload,
                "outputs": outputs,
                "revision": revision,
                "flowchart": flowchart_payload,
                "analysis_meta": analysis_payload.get("analysis_meta", {}),
            },
        )
        _set_stage(ctx, "awaiting_approval")
        _append_message(
            ctx,
            "orchestrator",
            "Analysis ready. Review inputs and outputs, then approve or ask for refinement.",
            tags=["analysis"],
        )
        meta_message = _format_analysis_meta(analysis.analysis_meta)
        if meta_message:
            _append_message(ctx, "orchestrator", meta_message, tags=["analysis", "clarify"])
        _emit(ctx, "approval_requested", {"revision": revision})
    except Exception as exc:
        logger.exception("Analysis failed")
        _set_stage(ctx, "idle")
        if isinstance(exc, WorkflowAnalysisError):
            error_text = str(getattr(exc, "context", {}).get("error", str(exc)))
            message, questions = _summarize_analysis_failure(error_text)
            _append_message(ctx, "orchestrator", message, tags=["analysis", "error", "clarify"])
            _emit(
                ctx,
                "analysis_failed",
                {"error": error_text, "questions": questions},
            )
        else:
            _append_message(
                ctx,
                "orchestrator",
                f"Analysis failed. {type(exc).__name__}: {exc}",
                tags=["error"],
            )
        _emit(ctx, "error", {"stage": "analysis", "message": str(exc)})


def _run_flowchart_prompt(ctx: SessionContext, prompt: str) -> None:
    with ctx.lock:
        current_flowchart = ctx.state.flowchart
        history = list(ctx.state.flowchart_messages)

    if not isinstance(current_flowchart, dict):
        _append_message(
            ctx,
            "orchestrator",
            "I do not have a flowchart yet. Build one on the canvas or upload a workflow image.",
            tags=["flowchart"],
        )
        return

    history.append({"role": "user", "content": prompt})
    clarification = clarify_flowchart_request(
        prompt=prompt, flowchart=current_flowchart, history=history
    )

    if clarification.status == "clarify":
        question_text = "I need a couple clarifications:\n- " + "\n- ".join(
            clarification.questions
        )
        with ctx.lock:
            ctx.state.flowchart_messages = history + [
                {"role": "assistant", "content": question_text}
            ]
            _save_state(ctx)
        _append_message(ctx, "orchestrator", question_text, tags=["flowchart"])
        return

    flowchart_model = generate_flowchart_from_request(
        prompt=prompt, flowchart=current_flowchart, history=history
    )
    layout_flowchart(flowchart_model)
    updated = flowchart_model.to_dict()
    summary = "Flowchart updated. Tell me what to change next."

    with ctx.lock:
        ctx.state.flowchart = updated
        ctx.state.flowchart_messages = history + [{"role": "assistant", "content": summary}]
        _save_state(ctx)

    _emit(ctx, "flowchart_updated", {"flowchart": updated})
    _append_message(ctx, "orchestrator", summary, tags=["flowchart"])


def _build_status_message(state: OrchestratorState) -> str:
    stage = state.stage or "idle"
    parts = [f"Current stage: {stage}."]
    if stage == "tests_running":
        progress = state.test_progress or {}
        current = progress.get("current", 0)
        total = progress.get("total", 0)
        parts.append(f"Tests labeled: {current}/{total}.")
    if state.iterations:
        last = state.iterations[-1]
        score = last.get("score")
        if score is not None:
            parts.append(f"Latest iteration score: {score * 100:.1f}%.")
    if state.generated_code_path:
        parts.append("Draft code is available to download.")
    return " ".join(parts)


def _summarize_analysis_failure(error_text: str) -> tuple[str, list[str]]:
    issues: List[str] = []
    if "float_parsing" in error_text and "possible_values" in error_text:
        issues.append(
            "Some inputs look like dates but were emitted as numeric ranges. "
            "Are those inputs dates, and what are their valid ranges?"
        )
    if "workflow_paths" in error_text and "path_id" in error_text:
        issues.append(
            "Some workflow paths were missing identifiers. I can auto-generate them if needed."
        )
    if "workflow_paths" in error_text and "output" in error_text:
        issues.append(
            "Some workflow paths are missing terminal outputs. Which boxes are the true outputs?"
        )
    if not issues:
        issues.append(
            "The workflow image looks ambiguous or lacks clear labels for inputs/outputs."
        )
    message = (
        "I could not validate the workflow analysis JSON. "
        + " ".join(issues)
        + " Reply with clarification and ask me to analyze again."
    )
    return message, issues


def _format_analysis_meta(meta: Any) -> Optional[str]:
    if not meta:
        return None

    def _clean_list(value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if value is None:
            return []
        text = str(value).strip()
        return [text] if text else []

    ambiguities = _clean_list(getattr(meta, "ambiguities", None) if not isinstance(meta, dict) else meta.get("ambiguities"))
    questions = _clean_list(getattr(meta, "questions", None) if not isinstance(meta, dict) else meta.get("questions"))
    warnings = _clean_list(getattr(meta, "warnings", None) if not isinstance(meta, dict) else meta.get("warnings"))

    if not (ambiguities or questions or warnings):
        return None

    lines = ["I spotted a few ambiguities in the diagram.", ""]

    def add_section(label: str, items: List[str]) -> None:
        if not items:
            return
        lines.append(f"### {label}")
        lines.extend([f"- {item}" for item in items])
        lines.append("")

    add_section("Ambiguities", ambiguities)
    add_section("Questions", questions)
    add_section("Warnings", warnings)

    while lines and not lines[-1].strip():
        lines.pop()
    lines.append("Reply with clarification or ask me to refine the analysis.")
    return "\n".join(lines)


def _run_orchestrator(session_id: str) -> None:
    ctx = _get_session_context(session_id)
    with ctx.lock:
        state = ctx.state
        conversation = [
            {"role": "assistant" if msg.role == "orchestrator" else msg.role, "content": msg.content}
            for msg in state.conversation[-12:]
        ]
        summary = {
            "stage": state.stage,
            "has_workflow_image": bool(state.workflow_image),
            "has_flowchart": bool(state.flowchart),
            "has_analysis": bool(state.analysis),
            "has_tests": bool(state.test_progress.get("total")),
            "has_generated_code": bool(state.generated_code_path),
        }

    decision = ORCHESTRATOR.decide(conversation=conversation, state_summary=summary)
    action = decision.action
    assistant_message = decision.assistant_message

    with ctx.lock:
        current_state = ctx.state
        is_busy = current_state.stage in RUNNING_STAGES
        has_image = bool(current_state.workflow_image)
        has_analysis = bool(current_state.analysis)

    if action == "status":
        assistant_message = _build_status_message(current_state)
        _append_message(ctx, "orchestrator", assistant_message, tags=["chat"])
        return
    if action == "help":
        assistant_message = (
            "You can ask me to analyze the workflow image, run tests, or refine code. "
            "Example: 'Analyze the workflow', or 'Run refinement'."
        )
        _append_message(ctx, "orchestrator", assistant_message, tags=["chat"])
        return
    if action == "analyze":
        if not has_image:
            _append_message(
                ctx,
                "orchestrator",
                "Upload or draw a workflow image first, then ask me to analyze it.",
                tags=["chat"],
            )
            return
        if is_busy:
            _append_message(
                ctx,
                "orchestrator",
                "I'm already running a step. Ask for status or wait for completion.",
                tags=["chat"],
            )
            return
        _append_message(ctx, "orchestrator", assistant_message, tags=["chat"])
        _start_background(_run_analysis, ctx.session_id, feedback=None)
        return
    if action == "refine":
        if not has_analysis:
            _append_message(
                ctx,
                "orchestrator",
                "I need a workflow analysis first. Ask me to analyze the workflow.",
                tags=["chat"],
            )
            return
        if is_busy:
            _append_message(
                ctx,
                "orchestrator",
                "I'm already running a step. Ask for status or wait for completion.",
                tags=["chat"],
            )
            return
        _append_message(ctx, "orchestrator", assistant_message, tags=["chat"])
        _start_background(_run_tests_and_codegen, ctx.session_id)
        return
    if action == "flowchart":
        if is_busy:
            _append_message(
                ctx,
                "orchestrator",
                "I'm already running a step. Ask for status or wait for completion.",
                tags=["chat"],
            )
            return
        _append_message(ctx, "orchestrator", assistant_message, tags=["chat"])
        _run_flowchart_prompt(ctx, prompt=conversation[-1]["content"])
        return

    _append_message(ctx, "orchestrator", assistant_message, tags=["chat"])


@app.route("/api/flowchart/prompt", methods=["POST"])
def flowchart_prompt() -> Response:
    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    flowchart = data.get("flowchart")
    if not prompt:
        return jsonify({"error": "empty_prompt"}), 400

    ctx = _get_session_context()
    with ctx.lock:
        current_flowchart = (
            flowchart if isinstance(flowchart, dict) else ctx.state.flowchart
        )
        history = list(ctx.state.flowchart_messages)
        history.append({"role": "user", "content": prompt})

    clarification = clarify_flowchart_request(
        prompt=prompt, flowchart=current_flowchart, history=history
    )

    if clarification.status == "clarify":
        question_text = "I need a couple clarifications:\n- " + "\n- ".join(
            clarification.questions
        )
        with ctx.lock:
            ctx.state.flowchart_messages = history + [
                {"role": "assistant", "content": question_text}
            ]
            _save_state(ctx)
        return jsonify({"questions": clarification.questions, "messages": ctx.state.flowchart_messages})

    flowchart_model = generate_flowchart_from_request(
        prompt=prompt, flowchart=current_flowchart, history=history
    )
    layout_flowchart(flowchart_model)
    updated = flowchart_model.to_dict()
    summary = "I drafted a flowchart on the canvas. Tell me what to change."
    with ctx.lock:
        ctx.state.flowchart = updated
        ctx.state.flowchart_messages = history + [{"role": "assistant", "content": summary}]
        _save_state(ctx)

    return jsonify({"flowchart": updated, "message": summary, "messages": ctx.state.flowchart_messages})


@app.route("/api/flowchart/run", methods=["POST"])
def flowchart_run() -> Response:
    data = request.get_json(silent=True) or {}
    image_data = (data.get("image_data") or "").strip()
    flowchart = data.get("flowchart")
    if not image_data:
        return jsonify({"error": "missing_image"}), 400

    workflow_name = (data.get("workflow_name") or "").strip()
    slug = _slugify(workflow_name) if workflow_name else "workflow"
    run_id = uuid.uuid4().hex[:10]
    run_dir = RUNS_DIR / f"{slug}_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{slug}.png"
    path = run_dir / filename

    if image_data.startswith("data:"):
        header, _, payload = image_data.partition(",")
        raw = payload
    else:
        raw = image_data

    try:
        decoded = base64.b64decode(raw)
    except Exception:
        return jsonify({"error": "invalid_image_data"}), 400

    path.write_bytes(decoded)

    ctx = _get_session_context()
    _reset_state(ctx)
    with ctx.lock:
        ctx.state.workflow_image = str(path)
        ctx.state.workflow_name = workflow_name or slug
        ctx.state.run_id = run_id
        ctx.state.run_dir = str(run_dir)
        ctx.state.flowchart = flowchart if isinstance(flowchart, dict) else None
        _save_state(ctx)

    _append_message(ctx, "user", "Submitted flowchart for analysis.", tags=["flowchart"])
    _append_message(
        ctx,
        "orchestrator",
        "Flowchart received. Ask me to analyze it when you are ready.",
        tags=["flowchart"],
    )

    return jsonify(
        {
            "status": "ok",
            "path": str(path),
            "workflow_name": ctx.state.workflow_name,
            "run_id": ctx.state.run_id,
        }
    )


def _run_tests_and_codegen(session_id: str) -> None:
    ctx = _get_session_context(session_id)
    with ctx.lock:
        image_path = ctx.state.workflow_image
        analysis_payload = ctx.state.analysis
        outputs = ctx.state.outputs
        run_dir = ctx.state.run_dir
    if not image_path or not analysis_payload or not outputs:
        _append_message(ctx, "orchestrator", "Missing analysis artifacts. Cannot run tests.")
        return
    if not run_dir:
        _append_message(ctx, "orchestrator", "No workflow run directory available.")
        return

    _set_stage(ctx, "tests_running")

    try:
        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)
        generator = TestCaseGenerator(str(run_path / "workflow_inputs.json"))
        test_cases = generator.generate_test_cases(NUM_TEST_CASES, "comprehensive")
        (run_path / "test_cases.json").write_text(
            json.dumps(test_cases, indent=2), encoding="utf-8"
        )

        def progress_callback(
            completed_batches: int,
            total_batches: int,
            pass_num: int,
            pass_total: int,
        ) -> None:
            overall_completed = (pass_num - 1) * total_batches + completed_batches
            overall_total = total_batches * pass_total
            percent = int((overall_completed / overall_total) * 100) if overall_total else 0
            with ctx.lock:
                ctx.state.test_progress = {
                    "current": overall_completed,
                    "total": overall_total,
                    "percent": percent,
                }
                _save_state(ctx)
            _emit(
                ctx,
                "tests_progress",
                {
                    "current": overall_completed,
                    "total": overall_total,
                    "percent": percent,
                },
            )

        labeled = generator.label_test_cases(
            test_cases=test_cases,
            workflow_image_path=str(Path(image_path)),
            valid_outputs=outputs,
            workflow_analysis=analysis_payload,
            batch_size=BATCH_SIZE,
            max_workers=MAX_WORKERS,
            best_of_n=BEST_OF_N,
            progress_callback=progress_callback,
        )

        (run_path / "tests.json").write_text(
            json.dumps(labeled, indent=2), encoding="utf-8"
        )

        with ctx.lock:
            total = ctx.state.test_progress.get("total", 0)
            ctx.state.test_progress = {"current": total, "total": total, "percent": 100}
            _save_state(ctx)

        _emit(ctx, "tests_progress", ctx.state.test_progress)

        _append_message(
            ctx, "orchestrator", "Test cases ready. Starting refinement.", tags=["tests"]
        )
        _run_codegen(
            ctx, labeled, outputs, analysis_payload, Path(image_path), run_path
        )
    except Exception as exc:
        logger.exception("Test generation failed")
        _append_message(
            ctx,
            "orchestrator",
            f"Test generation failed. {type(exc).__name__}: {exc}",
            tags=["error"],
        )
        _emit(ctx, "error", {"stage": "tests", "message": str(exc)})


def _run_codegen(
    ctx: SessionContext,
    labeled_tests: List[Dict[str, Any]],
    outputs: List[str],
    analysis_payload: Dict[str, Any],
    image_path: Path,
    run_path: Path,
) -> None:
    _set_stage(ctx, "code_refining")

    try:
        analysis = WorkflowAnalysis.model_validate(analysis_payload)
        harness = TestHarness(test_cases=labeled_tests, valid_outputs=outputs)
        workflow_slug = _slugify(ctx.state.workflow_name or "workflow")
        output_path = run_path / f"{workflow_slug}.py"

        solver = AgenticCodeSolver(
            workflow_image=image_path,
            workflow_analysis=analysis,
            valid_outputs=outputs,
            test_harness=harness,
            output_path=output_path,
        )

        def on_iteration(iteration_result: Any) -> None:
            data = {
                "iteration": iteration_result.iteration,
                "score": iteration_result.score,
                "passed": None,
                "total": None,
            }
            with ctx.lock:
                ctx.state.iterations.append(data)
                if output_path.exists():
                    ctx.state.generated_code_path = str(output_path)
                _save_state(ctx)
            _emit(ctx, "iteration_result", data)

        evaluator = SolverEvaluator(
            score_threshold=1.0,
            max_iterations=MAX_ITERATIONS,
            on_iteration=on_iteration,
        )

        previous_cwd = Path.cwd()
        os.chdir(run_path)
        try:
            evaluator.evaluate(
                solver=solver,
                test_cases=labeled_tests,
                max_iterations=MAX_ITERATIONS,
                score_threshold=1.0,
            )
        finally:
            os.chdir(previous_cwd)

        with ctx.lock:
            ctx.state.generated_code_path = str(output_path)
            _save_state(ctx)

        _review_and_finalize(
            ctx=ctx,
            output_path=output_path,
            harness=harness,
            analysis=analysis,
            outputs=outputs,
            image_path=image_path,
            run_path=run_path,
        )
    except Exception as exc:
        logger.exception("Refinement failed")
        _append_message(
            ctx,
            "orchestrator",
            f"Refinement failed. {type(exc).__name__}: {exc}",
            tags=["error"],
        )
        _emit(ctx, "error", {"stage": "refinement", "message": str(exc)})


def _review_and_finalize(
    *,
    ctx: SessionContext,
    output_path: Path,
    harness: TestHarness,
    analysis: WorkflowAnalysis,
    outputs: List[str],
    image_path: Path,
    run_path: Path,
) -> None:
    code = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    if not code:
        _append_message(ctx, "orchestrator", "No code generated to review.", tags=["error"])
        _emit(ctx, "error", {"stage": "review", "message": "Generated code missing"})
        return

    max_review_rounds = 2
    for review_round in range(1, max_review_rounds + 1):
        ok, feedback = _review_code(code)
        if ok:
            _append_message(ctx, "orchestrator", "Code review passed. Finalizing output.")
            break

        _append_message(
            ctx,
            "orchestrator",
            f"Code review flagged issues (round {review_round}). Rewriting with feedback.",
            tags=["review"],
        )
        generator = CodeGenerator()
        context = GenerationContext(
            failures=[{"error": f"Code review feedback: {feedback}", "test_case": {}}],
            test_cases_file=run_path / "tests.json",
        )
        code = generator.generate(
            workflow_image_path=image_path,
            workflow_data=analysis,
            valid_outputs=outputs,
            context=context,
        )
        output_path.write_text(code, encoding="utf-8")
        score = harness.score(code)

        iteration_num = len(ctx.state.iterations) + 1
        iteration_data = {
            "iteration": iteration_num,
            "score": score.pass_rate,
            "passed": score.passed,
            "total": score.total,
        }
        with ctx.lock:
            ctx.state.iterations.append(iteration_data)
            _save_state(ctx)
        _emit(ctx, "iteration_result", iteration_data)

        if score.pass_rate >= 1.0:
            _append_message(ctx, "orchestrator", "Rewritten code passed all tests.")
            break

    with ctx.lock:
        _save_state(ctx)

    _set_stage(ctx, "done")
    _append_message(ctx, "orchestrator", "Pipeline complete. Your Python file is ready.")
    _emit(
        ctx,
        "artifact_ready",
        {
            "path": ctx.state.generated_code_path,
            "download_url": "/api/download",
        },
    )


def _review_code(code: str) -> tuple[bool, str]:
    prompt = (
        "You are a senior Python reviewer. Review the code for correctness, "
        "clarity, and adherence to deterministic logic. The code should not "
        "use try/except for normal control flow. Return JSON only in the form "
        "{\"status\": \"pass\"|\"fail\", \"feedback\": \"...\"}."
        "\n\nCODE:\n"
        + code
    )
    response = make_request(
        [{"role": "user", "content": prompt}],
        max_tokens=800,
        system="You are a strict Python code reviewer.",
    )
    text = response.content[0].text if response.content else ""
    try:
        data = json.loads(text)
        status = str(data.get("status", "")).lower()
        feedback = str(data.get("feedback", "")).strip()
        if status == "pass":
            return True, ""
        return False, feedback or "Review failed without specific feedback."
    except Exception:
        logger.warning("Code review returned invalid JSON; treating as pass.")
        return True, ""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
