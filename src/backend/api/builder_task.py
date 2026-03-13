"""Lightweight task for subworkflow builds — runs headless with its own EventSink.

Unlike the parent ChatTask, a BuilderTask does not need a live SSE connection
at creation time. It creates its own EventSink and queues events independently.
The frontend connects via POST /api/chat/resume when the user navigates to
the subworkflow page — swap_sink replays accumulated content to the new stream.

Satisfies the Registrable protocol for TaskRegistry so resume, cancel, and
stale-purge all work identically to ChatTask.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from threading import Event
from typing import Any, Dict, List, Optional

from .sse import EventSink
from .tool_summaries import ToolSummaryTracker
from ..tools.constants import WORKFLOW_EDIT_TOOLS

logger = logging.getLogger(__name__)


@dataclass
class BuilderTask:
    """Manages a subworkflow build in a background thread.

    Provides the same callback interface the orchestrator expects
    (stream, on_tool_event, should_cancel, on_thinking) and the same
    resume interface the /api/chat/resume endpoint expects (swap_sink,
    done, thinking_chunks, stream_buffer).
    """

    # --- Core identity ---
    sink: EventSink
    workflow_id: str
    user_id: str
    task_id: str

    # --- Resume-compatible state ---
    done: Event = field(default_factory=Event)
    thinking_chunks: List[str] = field(default_factory=list)
    stream_buffer: str = ""

    # --- Tool tracking ---
    executed_tools: List[Dict[str, Any]] = field(default_factory=list)
    tool_summary: ToolSummaryTracker = field(default_factory=ToolSummaryTracker)

    # --- Orchestrator reference (set after construction) ---
    orchestrator: Any = None

    # --- Registrable protocol fields ---
    current_workflow_id: str = ""
    _cancelled: bool = False
    _notified: bool = False
    _created_at: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        self.current_workflow_id = self.workflow_id

    # --- Event emission ---

    def _emit(self, event: str, payload: dict) -> None:
        """Push an event to the builder's own SSE stream."""
        if self.current_workflow_id and "workflow_id" not in payload:
            payload["workflow_id"] = self.current_workflow_id
        self.sink.push(event, payload)

    # --- Orchestrator callbacks ---

    def is_cancelled(self) -> bool:
        """Check if this build has been cancelled or the sink disconnected."""
        return self._cancelled or self.sink.is_closed

    def stream_chunk(self, chunk: str) -> None:
        """Emit a streaming text chunk — accumulates for resume replay."""
        if self.is_cancelled():
            return
        self.stream_buffer += chunk
        self._emit("chat_stream", {"chunk": chunk, "task_id": self.task_id})

    def stream_thinking(self, chunk: str) -> None:
        """Emit a thinking chunk — accumulates for resume replay."""
        if not chunk or self.is_cancelled():
            return
        self.thinking_chunks.append(chunk)
        self._emit("chat_thinking", {"chunk": chunk, "task_id": self.task_id})

    def emit_user_message(self, content: str) -> None:
        """Emit the initial builder prompt so the frontend shows it."""
        self._emit("build_user_message", {"content": content})

    def emit_progress(self, status: str, event: str = "update") -> None:
        """Emit a progress indicator."""
        self._emit("chat_progress", {
            "event": event,
            "status": status,
            "task_id": self.task_id,
        })

    def flush_tool_summary(self) -> None:
        """Flush accumulated tool summaries into the stream as inline markdown."""
        summary = self.tool_summary.flush()
        if summary:
            self.stream_chunk(summary)

    def emit_response(self, response_text: str) -> None:
        """Emit the final chat_response — signals build completion."""
        self.flush_tool_summary()
        self._emit("chat_response", {
            "response": response_text,
            "tool_calls": self.executed_tools,
            "cancelled": self._cancelled,
        })

    def on_tool_event(
        self,
        event: str,
        tool: str,
        args: Dict[str, Any],
        result: Optional[Dict[str, Any]],
    ) -> None:
        """Handle tool lifecycle events — tracks calls and emits canvas updates.

        Mirrors ChatTask.on_tool_event for the subset of events relevant to
        background builds (no conversation_logger snapshots, no ask_question).
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

            # Emit canvas updates for workflow edit tools so nodes appear live
            if result.get("success") and tool in WORKFLOW_EDIT_TOOLS:
                action = result.get("action", tool)
                self._emit("workflow_update", {"action": action, "data": result})
                if self.orchestrator is not None:
                    self._emit("workflow_state_updated", {
                        "workflow_id": self.workflow_id,
                        "workflow": self.orchestrator.current_workflow,
                        "analysis": self.orchestrator.workflow_analysis,
                        "task_id": self.task_id,
                    })
        elif event == "tool_batch_complete":
            self.flush_tool_summary()

        # Skip further emissions when cancelled
        if self._cancelled:
            return

    # --- Resume support ---

    def swap_sink(self, new_sink: EventSink) -> None:
        """Swap the event sink for resume after page refresh.

        Replays accumulated thinking + stream content to the new sink,
        then routes all future events through it. Closes the old sink
        to end the stale SSE stream (or drain the unread queue).
        """
        # Signal reconnection
        new_sink.push("chat_progress", {
            "event": "resumed",
            "status": "Processing...",
            "task_id": self.task_id,
            "workflow_id": self.workflow_id,
        })
        # Replay accumulated thinking
        if self.thinking_chunks:
            new_sink.push("chat_thinking", {
                "chunk": "".join(self.thinking_chunks),
                "task_id": self.task_id,
                "workflow_id": self.workflow_id,
            })
        # Replay accumulated stream content
        if self.stream_buffer:
            new_sink.push("chat_stream", {
                "chunk": self.stream_buffer,
                "task_id": self.task_id,
                "workflow_id": self.workflow_id,
            })
        # Replay last workflow state so the canvas syncs
        if self.orchestrator is not None:
            new_sink.push("workflow_state_updated", {
                "workflow_id": self.workflow_id,
                "workflow": self.orchestrator.current_workflow,
                "analysis": self.orchestrator.workflow_analysis,
            })
        # Swap: close old sink, install new one
        old_sink = self.sink
        self.sink = new_sink
        old_sink.close()
