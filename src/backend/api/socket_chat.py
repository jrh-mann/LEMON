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

        try:
            response_text = convo.orchestrator.respond(
                message,
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
            return

        tool_calls = extract_tool_calls(response_text, include_result=False)
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
