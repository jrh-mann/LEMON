"""Socket chat workflow for the API server."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from threading import Event, Lock
from typing import Any, Dict, Optional
from uuid import uuid4

from flask import request
from flask_socketio import SocketIO

from .common import utc_now
from .conversations import ConversationStore
from .response_utils import extract_tool_calls, summarize_response
from ..utils.uploads import save_uploaded_image

logger = logging.getLogger("backend.api")

TOOL_STATUS_MESSAGES = {
    "analyze_workflow": "Subagent analyzed the workflow.",
    "publish_latest_analysis": "Analysis published to the canvas.",
    "get_current_workflow": "Loaded current workflow state.",
    "add_node": "Added a workflow node.",
    "modify_node": "Updated a workflow node.",
    "delete_node": "Removed a workflow node.",
    "add_connection": "Connections added.",
    "delete_connection": "Connections removed.",
    "batch_edit_workflow": "Applied workflow changes.",
}

_TASK_STATE: Dict[str, Dict[str, Any]] = {}
_TASK_LOCK = Lock()
_TASK_TTL_SECONDS = 1800.0


def _purge_stale_tasks_locked(now: float) -> None:
    stale = [
        task_id
        for task_id, state in _TASK_STATE.items()
        if now - state.get("created_at", now) > _TASK_TTL_SECONDS
    ]
    for task_id in stale:
        _TASK_STATE.pop(task_id, None)


def _register_task(task_id: str) -> None:
    with _TASK_LOCK:
        now = time.monotonic()
        _purge_stale_tasks_locked(now)
        _TASK_STATE.setdefault(
            task_id,
            {"cancelled": False, "notified": False, "created_at": now},
        )


def _cancel_task(task_id: str) -> None:
    with _TASK_LOCK:
        now = time.monotonic()
        _purge_stale_tasks_locked(now)
        state = _TASK_STATE.get(task_id)
        if not state:
            _TASK_STATE[task_id] = {"cancelled": True, "notified": False, "created_at": now}
            return
        state["cancelled"] = True


def _is_task_cancelled(task_id: str) -> bool:
    with _TASK_LOCK:
        _purge_stale_tasks_locked(time.monotonic())
        state = _TASK_STATE.get(task_id)
        return bool(state and state.get("cancelled"))


def _mark_task_notified(task_id: str) -> bool:
    with _TASK_LOCK:
        state = _TASK_STATE.get(task_id)
        if not state or state.get("notified"):
            return False
        state["notified"] = True
        return True


def _clear_task(task_id: str) -> None:
    with _TASK_LOCK:
        _TASK_STATE.pop(task_id, None)


def handle_socket_chat(
    socketio: SocketIO,
    *,
    conversation_store: ConversationStore,
    repo_root: Path,
    payload: Dict[str, Any],
) -> None:
    conversation_id = payload.get("conversation_id")
    message = payload.get("message", "")
    image_data = payload.get("image")
    workflow = payload.get("workflow")  # Extract workflow from chat payload
    task_id = payload.get("task_id")
    sid = request.sid

    if not isinstance(message, str) or not message.strip():
        socketio.emit("agent_error", {"task_id": task_id, "error": "message is required"}, to=sid)
        return

    if not isinstance(task_id, str) or not task_id.strip():
        task_id = uuid4().hex
    _register_task(task_id)

    def run_task() -> None:
        socketio.emit(
            "chat_progress",
            {"event": "start", "status": "Thinking...", "task_id": task_id},
            to=sid,
        )
        done = Event()
        executed_tools: list[dict[str, Any]] = []
        tool_counts: dict[str, int] = {}
        tool_order: list[str] = []

        def is_cancelled() -> bool:
            return _is_task_cancelled(task_id)

        def heartbeat() -> None:
            while not done.is_set():
                socketio.sleep(5)
                if done.is_set() or is_cancelled():
                    break
                socketio.emit(
                    "chat_progress",
                    {"event": "heartbeat", "status": "Analyzing...", "task_id": task_id},
                    to=sid,
                )

        socketio.start_background_task(heartbeat)
        try:
            convo = conversation_store.get_or_create(conversation_id)
            if isinstance(image_data, str) and image_data.strip():
                try:
                    save_uploaded_image(image_data, repo_root=repo_root)
                except Exception as exc:
                    logger.exception("Failed to save uploaded image")
                    socketio.emit(
                        "agent_error",
                        {"task_id": task_id, "error": f"Invalid image: {exc}"},
                        to=sid,
                    )
                    return

            did_stream = False

            def stream_chunk(chunk: str) -> None:
                nonlocal did_stream
                if is_cancelled():
                    return
                did_stream = True
                socketio.emit("chat_stream", {"chunk": chunk, "task_id": task_id}, to=sid)
                socketio.sleep(0)

            def note_tool(tool_name: str) -> None:
                if not tool_name:
                    return
                if tool_name not in tool_counts:
                    tool_counts[tool_name] = 0
                    tool_order.append(tool_name)
                tool_counts[tool_name] += 1

            def format_tool_summary(tool_name: str, count: int) -> str:
                base = TOOL_STATUS_MESSAGES.get(tool_name, f"Completed: {tool_name}.")
                if count > 1:
                    base = base.rstrip(".")
                    return f"{base} x{count}."
                return base

            def flush_tool_summary() -> None:
                if not tool_order:
                    return
                lines: list[str] = []
                for name in tool_order:
                    count = tool_counts.get(name, 0)
                    if count <= 0:
                        continue
                    lines.append(f"> {format_tool_summary(name, count)}")
                if lines:
                    stream_chunk("\n\n" + "\n".join(lines) + "\n\n")
                tool_counts.clear()
                tool_order.clear()

            def on_tool_event(
                event: str,
                tool: str,
                args: Dict[str, Any],
                result: Optional[Dict[str, Any]],
            ) -> None:
                if is_cancelled():
                    return
                if event == "tool_start":
                    executed_tools.append({"tool": tool, "arguments": args})
                if tool == "analyze_workflow":
                    status = "Analyzing workflow..."
                    socketio.emit(
                        "chat_progress",
                        {"event": event, "status": status, "tool": tool, "task_id": task_id},
                        to=sid,
                    )
                if event == "tool_complete":
                    note_tool(tool)
                if event == "tool_batch_complete":
                    flush_tool_summary()
                if tool == "publish_latest_analysis" and event == "tool_complete" and isinstance(result, dict):
                    flowchart = result.get("flowchart") if isinstance(result.get("flowchart"), dict) else None
                    if flowchart and flowchart.get("nodes"):
                        analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else None
                        socketio.emit(
                            "workflow_modified",
                            {
                                "action": "create_workflow",
                                "data": {
                                    "flowchart": flowchart,
                                    "analysis": analysis,
                                },
                            },
                            to=sid,
                        )

                # Handle workflow manipulation tools
                if event == "tool_complete" and isinstance(result, dict) and result.get("success"):
                    workflow_tools = [
                        "add_node",
                        "modify_node",
                        "delete_node",
                        "add_connection",
                        "delete_connection",
                        "batch_edit_workflow",
                    ]
                    if tool in workflow_tools:
                        socketio.emit(
                            "workflow_update",
                            {
                                "action": result.get("action"),
                                "data": result,
                            },
                            to=sid,
                        )

                    # Handle input management tools
                    input_tools = [
                        "add_workflow_input",
                        "remove_workflow_input",
                    ]
                    if tool in input_tools:
                        # Emit analysis update with current inputs
                        socketio.emit(
                            "analysis_updated",
                            {
                                "inputs": convo.orchestrator.workflow_analysis.get("inputs", []),
                                "outputs": convo.orchestrator.workflow_analysis.get("outputs", []),
                            },
                            to=sid,
                        )

            # Update workflow state from chat payload (atomic: workflow travels with message)
            if isinstance(workflow, dict):
                convo.update_workflow_state(workflow)

            # Sync workflow from session to orchestrator before responding
            convo.orchestrator.sync_workflow(lambda: convo.workflow_state)
            convo.orchestrator.sync_workflow_analysis(lambda: convo.workflow_analysis)

            response_text = convo.orchestrator.respond(
                message,
                has_image=bool(image_data),
                stream=stream_chunk,
                allow_tools=True,
                should_cancel=is_cancelled,
                on_tool_event=on_tool_event,
            )

            # Write orchestrator's workflow state back to session (preserve state across messages)
            convo.update_workflow_state(convo.orchestrator.current_workflow)
            convo.update_workflow_analysis(convo.orchestrator.workflow_analysis)

            if is_cancelled():
                if _mark_task_notified(task_id):
                    socketio.emit("chat_cancelled", {"task_id": task_id}, to=sid)
                return

            tool_calls = extract_tool_calls(response_text, include_result=False)
            if not tool_calls and executed_tools:
                tool_calls = executed_tools
            summary = summarize_response(response_text) if tool_calls else ""
            convo.updated_at = utc_now()

            socketio.emit(
                "chat_response",
                {
                    "response": summary if tool_calls else ("" if did_stream else response_text),
                    "conversation_id": convo.id,
                    "tool_calls": tool_calls,
                    "task_id": task_id,
                },
                to=sid,
            )
        except Exception as exc:
            logger.exception("Socket chat failed")
            if not is_cancelled():
                socketio.emit(
                    "agent_error",
                    {"task_id": task_id, "error": str(exc)},
                    to=sid,
                )
        finally:
            done.set()
            _clear_task(task_id)

    socketio.start_background_task(run_task)


def handle_cancel_task(
    socketio: SocketIO,
    *,
    payload: Dict[str, Any],
) -> None:
    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        return
    _cancel_task(task_id)
    if _mark_task_notified(task_id):
        socketio.emit("chat_cancelled", {"task_id": task_id}, to=request.sid)


def handle_sync_workflow(
    socketio: SocketIO,
    *,
    conversation_store: ConversationStore,
    payload: Dict[str, Any],
) -> None:
    """Handle full workflow sync from frontend.

    Called when:
    - User uploads and analyzes workflow
    - User opens workflow from library
    - User creates new workflow from scratch

    This establishes the backend as source of truth.
    Fire-and-forget - chat messages now carry workflow atomically.
    """
    conversation_id = payload.get("conversation_id")
    workflow = payload.get("workflow")
    source = payload.get("source", "unknown")  # 'upload' | 'library' | 'manual'
    sid = request.sid

    if not conversation_id:
        logger.warning("sync_workflow missing conversation_id")
        return

    if not isinstance(workflow, dict):
        logger.warning("sync_workflow invalid workflow format")
        return

    # Store in session
    convo = conversation_store.get_or_create(conversation_id)
    convo.update_workflow_state(workflow)

    logger.info(
        "Synced workflow conv=%s source=%s nodes=%d edges=%d",
        conversation_id,
        source,
        len(workflow.get("nodes", [])),
        len(workflow.get("edges", []))
    )

    # Acknowledge (for debugging)
    socketio.emit('workflow_synced', {
        'conversation_id': conversation_id,
        'nodes_count': len(workflow.get("nodes", [])),
        'edges_count': len(workflow.get("edges", []))
    }, to=sid)
