"""Socket chat workflow for the API server."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from flask import request
from flask_socketio import SocketIO

from .common import utc_now
from .conversations import ConversationStore
from .response_utils import extract_tool_calls, summarize_response
from ..utils.uploads import save_uploaded_image

logger = logging.getLogger("backend.api")


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
    sid = request.sid

    if not isinstance(message, str) or not message.strip():
        socketio.emit("agent_error", {"task_id": None, "error": "message is required"}, to=sid)
        return

    def run_task() -> None:
        socketio.emit("chat_progress", {"event": "start", "status": "Thinking..."}, to=sid)
        done = False
        executed_tools: list[dict[str, Any]] = []

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
        if isinstance(image_data, str) and image_data.strip():
            try:
                save_uploaded_image(image_data, repo_root=repo_root)
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
            if event == "tool_start":
                executed_tools.append({"tool": tool, "arguments": args})
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

        try:
            # Update workflow state from chat payload (atomic: workflow travels with message)
            if isinstance(workflow, dict):
                convo.update_workflow_state(workflow)

            # Sync workflow from session to orchestrator before responding
            convo.orchestrator.sync_workflow(lambda: convo.workflow_state)

            response_text = convo.orchestrator.respond(
                message,
                has_image=bool(image_data),
                stream=stream_chunk,
                allow_tools=True,
                on_tool_event=on_tool_event,
            )

            # Write orchestrator's workflow state back to session (preserve state across messages)
            convo.update_workflow_state(convo.orchestrator.current_workflow)
        except Exception as exc:
            logger.exception("Socket chat failed")
            socketio.emit(
                "agent_error",
                {"task_id": None, "error": str(exc)},
                to=sid,
            )
            return

        tool_calls = extract_tool_calls(response_text, include_result=False)
        if not tool_calls and executed_tools:
            tool_calls = executed_tools
        summary = summarize_response(response_text) if tool_calls else ""
        convo.updated_at = utc_now()
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
