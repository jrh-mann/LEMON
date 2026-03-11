"""Reusable callback class for background subworkflow builders.

Emits the same chat_* events as WsChatTask, but tags each event with
`workflow_id`. The frontend routes ALL events to chatStore.conversations[workflow_id]
-- both normal orchestrator chats and background builder chats use the same
per-workflow conversation map. No separate build buffer system.

All emit calls go through registry.send_to_sync() which dispatches to
the python-socketio AsyncServer for thread-safe async bridging.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from ..tools.constants import WORKFLOW_EDIT_TOOLS
from .tool_summaries import ToolSummaryTracker
from .ws_registry import ConnectionRegistry

logger = logging.getLogger(__name__)


class BackgroundBuilderCallbacks:
    """Emit chat_* events for a background builder, tagged with workflow_id.

    Used by create_subworkflow and update_subworkflow to provide the same
    rich event stream as the main orchestrator's WsChatTask.
    """

    def __init__(
        self,
        ws_registry: ConnectionRegistry,
        conn_id: str,
        workflow_id: str,
        user_id: str = "",
        orchestrator: Any | None = None,
        task_id: str | None = None,
    ) -> None:
        self.ws_registry = ws_registry
        self.conn_id = conn_id
        self.workflow_id = workflow_id
        self.user_id = user_id
        self.orchestrator = orchestrator
        self.task_id = task_id
        self.cancelled = False
        self.executed_tools: List[Dict[str, Any]] = []
        # ToolSummaryTracker injects inline markdown summaries (e.g. "> Added a workflow node.")
        # between tool rounds — matches WsChatTask behavior for visual structure in the stream.
        self.tool_summary = ToolSummaryTracker()
        # Resume-compatible fields: handle_resume_task reads these to replay
        # accumulated content and re-route events after a page refresh.
        # Matches the interface of WsChatTask so builders are resumable.
        self.done = threading.Event()
        self.thinking_chunks: List[str] = []
        self.stream_buffer: str = ""
        # TaskRegistry-compatible fields: the unified registry uses these to
        # index, purge stale entries, and support conn_id mutation on resume.
        import time
        self.current_workflow_id = workflow_id
        self._created_at = time.monotonic()
        self._cancelled = False  # registry's cached cancel flag
        self._notified = False
        self._conn_lock = threading.Lock()
        self._consecutive_send_failures = 0
        self._first_failure_time: float | None = None

    def _emit(self, event: str, payload: dict) -> None:
        """Emit via registry (sync, from background thread)."""
        if not self.ws_registry or not self.conn_id:
            return
        self.ws_registry.send_to_sync(self.conn_id, event, payload)

    def stream_chunk(self, chunk: str) -> None:
        """Emit chat_stream with workflow_id tag."""
        if self.cancelled:
            return
        self.stream_buffer += chunk  # Accumulate for replay on resume
        self._emit("chat_stream", {
            "chunk": chunk,
            "workflow_id": self.workflow_id,
        })

    def stream_thinking(self, chunk: str) -> None:
        """Emit chat_thinking with workflow_id tag."""
        if not chunk or self.cancelled:
            return
        self.thinking_chunks.append(chunk)  # Accumulate for replay on resume
        self._emit("chat_thinking", {
            "chunk": chunk,
            "workflow_id": self.workflow_id,
        })

    def emit_user_message(self, content: str) -> None:
        """Emit the initial user prompt so the frontend shows it during streaming."""
        self._emit("build_user_message", {
            "content": content,
            "workflow_id": self.workflow_id,
        })

    def emit_progress(self, status: str, event: str = "update") -> None:
        """Emit chat_progress with workflow_id tag."""
        self._emit("chat_progress", {
            "event": event,
            "status": status,
            "workflow_id": self.workflow_id,
        })

    def is_cancelled(self) -> bool:
        """Check if this build has been cancelled."""
        return self._cancelled or self.cancelled

    def cancel(self) -> None:
        """Mark this build as cancelled."""
        self.cancelled = True
        self._cancelled = True

    def flush_tool_summary(self) -> None:
        """Flush accumulated tool summaries into the stream as inline markdown."""
        summary = self.tool_summary.flush()
        if summary:
            self.stream_chunk(summary)

    def on_tool_event(
        self,
        event: str,
        tool: str,
        args: Dict[str, Any],
        result: Optional[Dict[str, Any]],
    ) -> None:
        """Handle tool lifecycle events — mirrors WsChatTask.on_tool_event.

        Tracks tool calls, injects inline tool summaries via ToolSummaryTracker,
        and emits workflow_update for edit tools so nodes appear on the canvas
        live during the build.
        """
        if event == "tool_start":
            self.executed_tools.append({
                "tool": tool,
                "arguments": args,
                "status": "running",
            })
        elif event == "tool_complete" and isinstance(result, dict):
            if result.get("skipped"):
                return
            success = True
            if "success" in result:
                success = bool(result.get("success"))
            # Track in ToolSummaryTracker for inline summaries
            self.tool_summary.note(tool, success=success)
            for entry in reversed(self.executed_tools):
                if entry.get("tool") == tool and "result" not in entry:
                    entry["result"] = result
                    entry["success"] = success
                    entry["status"] = "complete"
                    break

            if result.get("success") and tool in WORKFLOW_EDIT_TOOLS:
                action = result.get("action", tool)
                self._emit("workflow_update", {
                    "action": action,
                    "data": result,
                })
                if self.orchestrator is not None:
                    payload = {
                        "workflow_id": self.workflow_id,
                        "workflow": self.orchestrator.current_workflow,
                        "analysis": self.orchestrator.workflow_analysis,
                    }
                    if self.task_id:
                        payload["task_id"] = self.task_id
                    self._emit("workflow_state_updated", payload)
        elif event == "tool_batch_complete":
            # Flush accumulated summaries into the stream between tool rounds
            self.flush_tool_summary()

        # Skip further socket emissions when cancelled
        if self.cancelled:
            return

    def emit_response(self, response_text: str) -> None:
        """Emit chat_response with workflow_id tag — signals build complete."""
        # Flush any remaining tool summaries before the final response
        self.flush_tool_summary()
        self._emit("chat_response", {
            "response": response_text,
            "workflow_id": self.workflow_id,
            "tool_calls": self.executed_tools,
            "cancelled": self.cancelled,
        })
