"""SSE event channel — owns the sink, replay buffers, and emit logic.

Extracted from ChatTask. Thread-safe swap_sink for resume after page refresh.
All SSE event emission for a chat task goes through this channel.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional

from .sse import EventSink
from .registry import task_registry


class ChatEventChannel:
    """Manages SSE transport for a single chat task.

    Owns the EventSink and replay buffers (thinking_chunks, stream_buffer,
    _last_workflow_state). All event emission goes through this channel.

    Thread safety: a lock guards sink swap and emit to prevent the race
    where swap_sink replays to a new sink while publish() writes to the old one.
    """

    def __init__(
        self,
        sink: EventSink,
        task_id: str,
        workflow_id_fn: Callable[[], Optional[str]],
    ) -> None:
        """
        Args:
            sink: Initial EventSink to push SSE events to.
            task_id: Owning task's ID (included in every event payload).
            workflow_id_fn: Zero-arg callable returning the current workflow_id.
                           Avoids storing a mutable string that can go stale.
                           ChatTask passes ``lambda: self.current_workflow_id``.
        """
        self._sink = sink
        self._task_id = task_id
        self._workflow_id_fn = workflow_id_fn
        self._lock = threading.Lock()

        # Replay buffers — accumulated content replayed on resume
        self.stream_buffer: str = ""
        self.thinking_chunks: List[str] = []
        self.did_stream: bool = False
        self._last_workflow_state: Optional[Dict[str, Any]] = None

    # --- Core emission ---

    @property
    def sink(self) -> EventSink:
        """The current underlying EventSink. Exposed read-only for
        external code that needs it (chat_routes cancel, orchestrator event_sink)."""
        return self._sink

    def publish(self, event: str, payload: dict) -> None:
        """Push an event to the SSE stream.

        Automatically includes workflow_id so the frontend can route
        events to the correct per-workflow conversation.
        """
        wf_id = self._workflow_id_fn()
        with self._lock:
            if wf_id and "workflow_id" not in payload:
                payload["workflow_id"] = wf_id
            self._sink.push(event, payload)

    def publish_workflow_state(self, payload: Dict[str, Any]) -> None:
        """Emit workflow_state_updated and cache for resume replay."""
        with self._lock:
            self._last_workflow_state = payload
        self.publish("workflow_state_updated", payload)

    def publish_progress(
        self, event: str, status: str, *, tool: Optional[str] = None,
    ) -> None:
        """Emit a chat_progress event."""
        payload: Dict[str, Any] = {
            "event": event, "status": status, "task_id": self._task_id,
        }
        if tool:
            payload["tool"] = tool
        self.publish("chat_progress", payload)

    def publish_error(self, error: str) -> None:
        """Emit an agent_error event."""
        self.publish("agent_error", {"task_id": self._task_id, "error": error})

    def publish_cancelled(self, task_id: str) -> None:
        """Emit chat_cancelled (idempotent via task_registry.mark_notified)."""
        if task_registry.mark_notified(task_id):
            self.publish("chat_cancelled", {"task_id": task_id})

    # --- Streaming callbacks (passed to orchestrator) ---

    def stream_chunk(self, chunk: str) -> None:
        """Accumulate and emit a text chunk.

        Passed as orchestrator's ``stream`` callback.
        """
        self.did_stream = True
        self.stream_buffer += chunk
        self.publish("chat_stream", {"chunk": chunk, "task_id": self._task_id})

    def stream_thinking(self, chunk: str) -> None:
        """Accumulate and emit a thinking chunk.

        Passed as orchestrator's ``on_thinking`` callback.
        """
        if not chunk:
            return
        self.thinking_chunks.append(chunk)
        self.publish("chat_thinking", {"chunk": chunk, "task_id": self._task_id})

    # --- Resume ---

    def swap_sink(self, new_sink: EventSink) -> None:
        """Swap the underlying sink for resume. Replays accumulated content.

        Thread-safe: holds the lock during the entire swap+replay so no
        concurrent publish() writes to the old sink after the swap.
        """
        wf_id = self._workflow_id_fn() or ""
        with self._lock:
            # Progress event so frontend knows it's reconnected
            new_sink.push("chat_progress", {
                "event": "resumed",
                "status": "Processing...",
                "task_id": self._task_id,
                "workflow_id": wf_id,
            })
            # Replay accumulated thinking
            if self.thinking_chunks:
                new_sink.push("chat_thinking", {
                    "chunk": "".join(self.thinking_chunks),
                    "task_id": self._task_id,
                    "workflow_id": wf_id,
                })
            # Replay accumulated stream content
            if self.stream_buffer:
                new_sink.push("chat_stream", {
                    "chunk": self.stream_buffer,
                    "task_id": self._task_id,
                    "workflow_id": wf_id,
                })
            # Replay last workflow state so the canvas syncs
            if self._last_workflow_state:
                new_sink.push("workflow_state_updated", {
                    **self._last_workflow_state,
                    "workflow_id": wf_id,
                })
            # Swap: close old sink, install new one
            old_sink = self._sink
            self._sink = new_sink
            old_sink.close()

    def close(self) -> None:
        """Close the underlying sink. Called in ChatTask.run() finally block."""
        self._sink.close()
