"""Reusable callback class for background subworkflow builders.

Emits the same chat_* socket events as SocketChatTask, but tags each
event with `workflow_id` instead of `task_id`. The frontend routes
events by checking for workflow_id — if present and matching the
currently viewed workflow, they go to workflowStore; otherwise they
go to chatStore as usual.

This unifies the event infrastructure so background builders get
thinking, progress, streaming, tool tracking, and cancellation
support — the same features the main orchestrator has.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..tools.constants import WORKFLOW_EDIT_TOOLS

logger = logging.getLogger(__name__)


class BackgroundBuilderCallbacks:
    """Emit chat_* events for a background builder, tagged with workflow_id.

    Used by create_subworkflow and update_subworkflow to provide the same
    rich event stream as the main orchestrator's SocketChatTask.
    """

    def __init__(self, socketio: Any, sid: str, workflow_id: str) -> None:
        self.socketio = socketio
        self.sid = sid
        self.workflow_id = workflow_id
        self.cancelled = False
        self.executed_tools: List[Dict[str, Any]] = []

    def stream_chunk(self, chunk: str) -> None:
        """Emit chat_stream with workflow_id tag."""
        if self.cancelled or not self.socketio or not self.sid:
            return
        self.socketio.emit("chat_stream", {
            "chunk": chunk,
            "workflow_id": self.workflow_id,
        }, to=self.sid)

    def stream_thinking(self, chunk: str) -> None:
        """Emit chat_thinking with workflow_id tag."""
        if not chunk or self.cancelled or not self.socketio or not self.sid:
            return
        self.socketio.emit("chat_thinking", {
            "chunk": chunk,
            "workflow_id": self.workflow_id,
        }, to=self.sid)

    def emit_progress(self, status: str, event: str = "update") -> None:
        """Emit chat_progress with workflow_id tag."""
        if not self.socketio or not self.sid:
            return
        self.socketio.emit("chat_progress", {
            "event": event,
            "status": status,
            "workflow_id": self.workflow_id,
        }, to=self.sid)

    def is_cancelled(self) -> bool:
        """Check if this build has been cancelled."""
        return self.cancelled

    def cancel(self) -> None:
        """Mark this build as cancelled."""
        self.cancelled = True

    def on_tool_event(
        self,
        event: str,
        tool: str,
        args: Dict[str, Any],
        result: Optional[Dict[str, Any]],
    ) -> None:
        """Handle tool lifecycle events — mirrors SocketChatTask.on_tool_event.

        Tracks tool calls and emits workflow_update for edit tools so nodes
        appear on the canvas live during the build.
        """
        if event == "tool_start":
            self.executed_tools.append({
                "tool": tool,
                "arguments": args,
                "status": "running",
            })
        elif event == "tool_complete" and isinstance(result, dict):
            # Update tool entry with result
            for entry in reversed(self.executed_tools):
                if entry.get("tool") == tool and "result" not in entry:
                    entry["result"] = result
                    entry["success"] = bool(result.get("success"))
                    entry["status"] = "complete"
                    break

            # Emit workflow_update for edit tools so nodes appear on canvas live
            if result.get("success") and tool in WORKFLOW_EDIT_TOOLS:
                if self.socketio and self.sid:
                    action = result.get("action", tool)
                    self.socketio.emit("workflow_update", {
                        "action": action,
                        "data": result,
                    }, to=self.sid)

    def emit_response(self, response_text: str) -> None:
        """Emit chat_response with workflow_id tag — signals build complete."""
        if not self.socketio or not self.sid:
            return
        self.socketio.emit("chat_response", {
            "response": response_text,
            "workflow_id": self.workflow_id,
            "tool_calls": self.executed_tools,
            "cancelled": self.cancelled,
        }, to=self.sid)
