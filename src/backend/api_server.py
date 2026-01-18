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
from .tools import AnalyzeWorkflowTool, PublishLatestAnalysisTool, ToolRegistry

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


def _extract_tool_calls(
    response_text: str, *, include_result: bool = True
) -> List[Dict[str, Any]]:
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict) and payload.get("source") == "subagent":
        tool = payload.get("tool") or "unknown"
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        result = data if include_result else {"session_id": data.get("session_id")}
        return [{"tool": tool, "arguments": {}, "result": result}]
    return []


def _extract_flowchart(response_text: str) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("source") != "subagent":
        return None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    flowchart = data.get("flowchart")
    if isinstance(flowchart, dict) and flowchart.get("nodes") is not None:
        return flowchart
    analysis = data.get("analysis") if isinstance(data.get("analysis"), dict) else {}
    flowchart = analysis.get("flowchart")
    if isinstance(flowchart, dict) and flowchart.get("nodes") is not None:
        return flowchart
    return None


def _summarize_response(response_text: str) -> str:
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        return response_text
    if not isinstance(payload, dict) or payload.get("source") != "subagent":
        return response_text
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    analysis = data.get("analysis") if isinstance(data.get("analysis"), dict) else {}
    inputs = analysis.get("inputs") if isinstance(analysis.get("inputs"), list) else []
    outputs = analysis.get("outputs") if isinstance(analysis.get("outputs"), list) else []
    doubts = analysis.get("doubts") if isinstance(analysis.get("doubts"), list) else []

    def _fmt_items(items: list, key: str) -> str:
        lines = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get(key) or ""
            typ = item.get("type")
            if typ:
                lines.append(f"- {name} ({typ})")
            else:
                lines.append(f"- {name}")
        return "\n".join(lines) if lines else "- None"

    inputs_text = _fmt_items(inputs, "input")
    outputs_text = _fmt_items(outputs, "output")
    doubts_text = "\n".join(f"- {d}" for d in doubts) if doubts else "- None"

    return (
        "Analysis complete.\n\n"
        "Inputs:\n"
        f"{inputs_text}\n\n"
        "Outputs:\n"
        f"{outputs_text}\n\n"
        "Doubts:\n"
        f"{doubts_text}"
    )


def _emit_stream_chunks(text: str, *, chunk_size: int = 1000) -> None:
    if not text:
        return
    for idx in range(0, len(text), chunk_size):
        emit("chat_stream", {"chunk": text[idx : idx + chunk_size]})


def build_orchestrator() -> Orchestrator:
    registry = ToolRegistry()
    registry.register(AnalyzeWorkflowTool(_repo_root()))
    registry.register(PublishLatestAnalysisTool(_repo_root()))
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
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    logger=True,
    engineio_logger=True,
    max_http_buffer_size=10 * 1024 * 1024,
    async_mode="threading",
)


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

    response_text = convo.orchestrator.respond(
        message,
        image_name=None,
        has_image=bool(image_data),
        allow_tools=True,
    )
    tool_calls = _extract_tool_calls(response_text, include_result=False)
    response_summary = _summarize_response(response_text)
    flowchart = _extract_flowchart(response_text)
    convo.updated_at = _utc_now()
    return jsonify(
        {
            "conversation_id": convo.id,
            "response": response_summary,
            "tool_calls": tool_calls,
            "flowchart": flowchart,
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


@socketio.on_error_default  # type: ignore[misc]
def default_socket_error(exc: Exception) -> None:
    logger.exception("Socket error: %s", exc)


@socketio.on("connect_error")
def socket_connect_error(data: Any) -> None:
    logger.error("Socket connect_error data=%s", data)


@app.before_request
def log_request() -> None:
    logger.info(
        "HTTP %s %s from %s",
        request.method,
        request.path,
        request.remote_addr,
    )


@socketio.on("chat")
def socket_chat(payload: Dict[str, Any]) -> None:
    session_id = payload.get("session_id")
    conversation_id = payload.get("conversation_id")
    message = payload.get("message", "")
    image_data = payload.get("image")
    sid = request.sid

    if not isinstance(message, str) or not message.strip():
        socketio.emit("agent_error", {"task_id": None, "error": "message is required"}, to=sid)
        return

    def run_task() -> None:
        socketio.emit("chat_progress", {"event": "start", "status": "Thinking..."}, to=sid)
        done = False

        def heartbeat() -> None:
            while not done:
                socketio.sleep(5)
                if done:
                    break
                socketio.emit(
                    "chat_progress",
                    {"event": "heartbeat", "status": "Analyzing..."},
                    to=sid,
                )

        socketio.start_background_task(heartbeat)

        convo = conversation_store.get_or_create(conversation_id)
        image_name = None
        if isinstance(image_data, str) and image_data.strip():
            try:
                image_name = _save_uploaded_image(image_data)
            except Exception as exc:
                logger.exception("Failed to save uploaded image")
                socketio.emit(
                    "agent_error",
                    {"task_id": None, "error": f"Invalid image: {exc}"},
                    to=sid,
                )
                return

        did_stream = False

        def stream_chunk(chunk: str) -> None:
            nonlocal did_stream
            did_stream = True
            socketio.emit("chat_stream", {"chunk": chunk}, to=sid)
            socketio.sleep(0)

        def on_tool_event(
            event: str,
            tool: str,
            args: Dict[str, Any],
            result: Optional[Dict[str, Any]],
        ) -> None:
            if tool == "analyze_workflow":
                status = "Analyzing workflow..."
                socketio.emit(
                    "chat_progress",
                    {"event": event, "status": status, "tool": tool},
                    to=sid,
                )
            if tool == "publish_latest_analysis" and event == "tool_complete" and isinstance(result, dict):
                flowchart = result.get("flowchart") if isinstance(result.get("flowchart"), dict) else None
                if flowchart and flowchart.get("nodes"):
                    socketio.emit(
                        "workflow_modified",
                        {
                            "action": "create_workflow",
                            "data": flowchart,
                        },
                        to=sid,
                    )

        try:
            response_text = convo.orchestrator.respond(
                message,
                image_name=None,
                has_image=bool(image_data),
                stream=stream_chunk,
                allow_tools=True,
                on_tool_event=on_tool_event,
            )
        except Exception as exc:
            logger.exception("Socket chat failed")
            socketio.emit(
                "agent_error",
                {"task_id": None, "error": str(exc)},
                to=sid,
            )
            done = True
            return

        tool_calls = _extract_tool_calls(response_text, include_result=False)
        flowchart = _extract_flowchart(response_text)
        summary = _summarize_response(response_text) if tool_calls else ""
        convo.updated_at = _utc_now()
        done = True

        socketio.emit(
            "chat_response",
            {
                "response": summary if tool_calls else ("" if did_stream else response_text),
                "conversation_id": convo.id,
                "tool_calls": tool_calls,
                "task_id": None,
            },
            to=sid,
        )

    socketio.start_background_task(run_task)
