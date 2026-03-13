"""SSE-based chat task — manages a single chat turn in a background thread.

Delegates SSE transport to ChatEventChannel. Events are pushed to a queue
that FastAPI yields as SSE.

No heartbeat thread needed (HTTP keepalive handles it).
No dead connection detection needed (sink.is_closed detects client disconnect).
No conn_id locking needed (channel handles sink swap with a lock).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Any, Dict, Optional

import anthropic

from .chat_event_channel import ChatEventChannel
from .chat_session import (
    save_uploaded_files,
    sync_payload_workflow,
    sync_orchestrator_from_convo,
    sync_convo_from_orchestrator,
    persist_conversation_metadata,
)
from .chat_turn_runner import ChatRuntimePorts, run_turn
from .common import utc_now
from .conversations import Conversation, ConversationStore
from .response_utils import extract_tool_calls
from .sse import EventSink
from .task_registry import task_registry
from .tool_event_projector import ToolEventProjector
from ..agents.turn import TurnStatus
from ..storage.conversation_log import ConversationLogger
from ..storage.workflows import WorkflowStore

logger = logging.getLogger("backend.api")

# Maximum wall-clock time a single chat turn can run before being killed.
# Prevents zombie tasks from LLM hangs or tool deadlocks.
_TASK_TIMEOUT_SECONDS = 600.0


@dataclass
class ChatTask:
    """Manages a single chat turn — runs in a background thread.

    Delegates SSE transport to ChatEventChannel for thread-safe emit/swap.
    """

    sink: EventSink
    conversation_store: ConversationStore
    repo_root: Path
    workflow_store: WorkflowStore
    user_id: str
    task_id: str
    message: str
    conversation_id: Optional[str]
    files_data: list[dict[str, Any]]
    workflow: Optional[Dict[str, Any]]
    analysis: Optional[Dict[str, Any]]
    current_workflow_id: Optional[str] = None
    open_tabs: Optional[list[Dict[str, Any]]] = None
    done: Event = field(default_factory=Event)
    convo: Optional[Conversation] = None
    img_annotations: Optional[list[dict[str, Any]]] = None
    saved_file_paths: list[dict[str, Any]] = field(default_factory=list)
    # Persistent audit log for the conversation lifecycle
    conversation_logger: Optional[ConversationLogger] = None
    # Cached cancellation flag — set by TaskRegistry.cancel()
    _cancelled: bool = False
    # Whether a chat_cancelled event has already been emitted for this task
    _notified: bool = False
    # Timestamp for stale task purging in TaskRegistry
    _created_at: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        """Construct the event channel and tool event projector."""
        self.channel = ChatEventChannel(
            sink=self.sink,
            task_id=self.task_id,
            workflow_id_fn=lambda: self.current_workflow_id,
        )
        # Projector uses late-binding lambdas — self.convo is None at
        # construction time and set during run().
        self._projector = ToolEventProjector(
            task_id=self.task_id,
            publish=self.channel.publish,
            publish_workflow_state=self.channel.publish_workflow_state,
            emit_progress=self.emit_progress,
            stream_chunk=self.stream_chunk,
            is_cancelled=self.is_cancelled,
            get_workflow_state_payload=self._workflow_state_payload,
            get_workflow_analysis=lambda: (
                self.convo.orchestrator.workflow_analysis if self.convo else {}
            ),
            conversation_logger=self.conversation_logger,
            get_convo_id=lambda: self.convo.id if self.convo else None,
            get_current_workflow=lambda: (
                self.convo.orchestrator.current_workflow if self.convo else None
            ),
        )

    # --- Transport delegates (external contract preserved) ---

    @property
    def thinking_chunks(self) -> list[str]:
        """Accumulated thinking chunks — delegated to channel."""
        return self.channel.thinking_chunks

    @property
    def stream_buffer(self) -> str:
        """Accumulated stream text — delegated to channel."""
        return self.channel.stream_buffer

    @property
    def did_stream(self) -> bool:
        """Whether any content was streamed — delegated to channel."""
        return self.channel.did_stream

    @property
    def executed_tools(self) -> list[dict[str, Any]]:
        """Tool audit trail — delegated to projector."""
        return self._projector.executed_tools

    @property
    def tool_summary(self):
        """Batched tool progress tracker — delegated to projector."""
        return self._projector.tool_summary

    def _emit(self, event: str, payload: dict) -> None:
        """Push an event to the SSE stream (delegates to channel)."""
        self.channel.publish(event, payload)

    def emit_progress(self, event: str, status: str, *, tool: Optional[str] = None) -> None:
        self.channel.publish_progress(event, status, tool=tool)

    def emit_error(self, error: str) -> None:
        if self.is_cancelled():
            return
        self.channel.publish_error(error)

    def emit_cancelled(self) -> None:
        self.channel.publish_cancelled(self.task_id)

    def stream_chunk(self, chunk: str) -> None:
        """Stream an SDK chunk to the frontend. Cancellation-guarded."""
        if self.is_cancelled():
            return
        self.channel.stream_chunk(chunk)

    def stream_thinking(self, chunk: str) -> None:
        """Stream LLM reasoning/thinking chunks. Cancellation-guarded."""
        if self.is_cancelled():
            return
        self.channel.stream_thinking(chunk)

    def swap_sink(self, new_sink: EventSink) -> None:
        """Swap the event sink for resume after page refresh (delegates to channel)."""
        self.channel.swap_sink(new_sink)
        # Keep self.sink in sync for external code that accesses task.sink directly
        # (e.g. chat_routes.py cancel endpoint pushes to task.sink)
        self.sink = self.channel.sink

    # --- Helpers ---

    def is_cancelled(self) -> bool:
        """Check cancellation flag (fast path — no lock needed)."""
        if self._cancelled:
            return True
        # Also check if the client disconnected (SSE stream closed)
        if self.channel.sink.is_closed:
            return True
        return False

    def _timeout_watchdog(self) -> None:
        """Kill the task if it exceeds the wall-clock timeout.

        Replaces the old heartbeat thread. No need to emit heartbeat events —
        SSE keepalive comments handle proxy timeout prevention.
        """
        start = time.monotonic()
        while not self.done.is_set():
            self.done.wait(5)
            if self.done.is_set() or self.is_cancelled():
                break
            elapsed = time.monotonic() - start
            if elapsed > _TASK_TIMEOUT_SECONDS:
                logger.error(
                    "Task %s timed out (%.0fs > %.0fs) — cancelling",
                    self.task_id, elapsed, _TASK_TIMEOUT_SECONDS,
                )
                self._cancelled = True
                self.emit_error(
                    "Task timed out — please try again with a simpler request."
                )
                break

    def flush_tool_summary(self) -> None:
        """Flush accumulated tool summary — delegated to projector."""
        self._projector.flush_tool_summary()

    def _workflow_state_payload(self) -> Optional[Dict[str, Any]]:
        """Build workflow state payload from current conversation."""
        if not self.convo:
            return None
        return {
            "workflow_id": self.convo.orchestrator.current_workflow_id,
            "workflow": self.convo.orchestrator.current_workflow,
            "analysis": self.convo.orchestrator.workflow_analysis,
            "task_id": self.task_id,
        }

    def on_tool_event(
        self,
        event: str,
        tool: str,
        args: Dict[str, Any],
        result: Optional[Dict[str, Any]],
    ) -> None:
        """Dispatch tool lifecycle events — delegated to projector."""
        self._projector.on_tool_event(event, tool, args, result)

    # --- Session helpers (delegated to chat_session module) ---

    def _save_uploaded_files(self) -> bool:
        """Save uploaded files to disk — delegates to chat_session."""
        ok, paths = save_uploaded_files(
            files_data=self.files_data,
            repo_root=self.repo_root,
            img_annotations=self.img_annotations,
            emit_error=self.emit_error,
        )
        self.saved_file_paths = paths
        return ok

    def _sync_payload_workflow(self) -> None:
        if self.convo:
            sync_payload_workflow(self.convo, self.workflow, self.analysis)

    def _sync_orchestrator_from_convo(self) -> None:
        if not self.convo:
            return
        sync_orchestrator_from_convo(
            convo=self.convo,
            workflow_id=self.current_workflow_id,
            user_id=self.user_id,
            repo_root=self.repo_root,
            workflow_store=self.workflow_store,
            event_sink=self.channel.sink,
            open_tabs=self.open_tabs,
            conversation_logger=self.conversation_logger,
            publish=self.channel.publish,
        )

    def _sync_convo_from_orchestrator(self) -> None:
        if self.convo:
            sync_convo_from_orchestrator(self.convo)

    def _emit_response(self, response_text: str, cancelled: bool = False) -> None:
        tool_calls = extract_tool_calls(response_text, include_result=False)
        if not tool_calls and self.executed_tools:
            tool_calls = self.executed_tools
        if self.convo:
            self.convo.updated_at = utc_now()
        # If content was already streamed via chat_stream events, don't send it
        # again in chat_response — the frontend already has it in streamingContent.
        # Only include response text when nothing was streamed (e.g. legacy sync endpoint).
        response_field = "" if self.did_stream else response_text
        if not response_field and not self.did_stream and not cancelled:
            logger.warning(
                "Emitting empty chat_response (no stream, no text, no tools) task=%s",
                self.task_id,
            )
        payload: Dict[str, Any] = {
            "response": response_field,
            "conversation_id": self.convo.id if self.convo else "",
            "tool_calls": tool_calls,
            "task_id": self.task_id,
        }
        if cancelled:
            payload["cancelled"] = True
        self._emit("chat_response", payload)

    # --- Audit logging helpers ---

    def _log_thinking(self) -> None:
        """Log accumulated thinking chunks to the audit trail."""
        if not (self.conversation_logger and self.convo and self.thinking_chunks):
            return
        try:
            self.conversation_logger.log_thinking(
                self.convo.id, "".join(self.thinking_chunks), task_id=self.task_id,
            )
        except Exception:
            logger.error(
                "Failed to log thinking to audit trail: conv=%s",
                self.convo.id if self.convo else "?", exc_info=True,
            )

    def _persist_conversation_metadata(self) -> None:
        """Persist conversation metadata — delegates to chat_session."""
        if not (self.current_workflow_id and self.workflow_store and self.convo):
            return
        persist_conversation_metadata(
            workflow_id=self.current_workflow_id,
            user_id=self.user_id,
            convo=self.convo,
            workflow_store=self.workflow_store,
            repo_root=self.repo_root,
            saved_file_paths=self.saved_file_paths,
        )

    # --- Main run loop ---

    def run(self) -> None:
        """Execute one chat turn: bootstrap → run_turn → emit → cleanup.

        Delegates the Turn lifecycle (create, respond, complete/cancel/fail)
        to run_turn(). This method handles bootstrap, SSE emission, and
        cleanup only.
        """
        self.emit_progress("start", "Thinking...")
        threading.Thread(target=self._timeout_watchdog, daemon=True).start()

        try:
            # --- Bootstrap ---
            self.convo = self.conversation_store.get_or_create(self.conversation_id)
            if not self._save_uploaded_files():
                return
            self._sync_payload_workflow()
            self._sync_orchestrator_from_convo()
            self._persist_conversation_metadata()

            # --- Execute turn ---
            ports = ChatRuntimePorts(
                stream_chunk=self.stream_chunk,
                stream_thinking=self.stream_thinking,
                on_tool_event=self.on_tool_event,
                is_cancelled=self.is_cancelled,
                get_stream_buffer=lambda: self.stream_buffer,
                conversation_logger=self.conversation_logger,
            )
            result = run_turn(
                convo=self.convo,
                message=self.message,
                task_id=self.task_id,
                user_id=self.user_id,
                workflow_id=self.current_workflow_id,
                saved_file_paths=self.saved_file_paths,
                ports=ports,
            )

            # --- Post-turn emission ---
            self._log_thinking()
            self._sync_convo_from_orchestrator()

            if result.status == TurnStatus.COMPLETED:
                self._emit("context_status", {
                    "usage_pct": result.context_usage_pct,
                    "input_tokens": result.input_tokens,
                    "message_count": result.message_count,
                })
                self._emit_response(result.response_text)
            elif result.cancelled:
                self._emit_response(result.response_text, cancelled=True)
                self.emit_cancelled()
            elif result.status == TurnStatus.FAILED:
                if isinstance(result.error, anthropic.RateLimitError):
                    self._emit("agent_error", {
                        "task_id": self.task_id,
                        "error": str(result.error),
                        "transient": True,
                    })
                else:
                    self.emit_error(
                        f"Something went wrong: {type(result.error).__name__}. Please try again."
                    )

        except Exception as exc:
            # Bootstrap failures (file save, workflow persist, etc.)
            logger.exception("Chat task bootstrap failed: task=%s", self.task_id)
            self.emit_error(f"Something went wrong: {type(exc).__name__}. Please try again.")

        finally:
            self.done.set()
            task_registry.unregister(self)
            # Close our SSE stream. Builder tasks have their own independent
            # sinks so this won't affect them.
            self.channel.close()
            # Clear building flag so the workflow doesn't appear stuck
            if self.current_workflow_id and self.workflow_store:
                try:
                    self.workflow_store.update_workflow(
                        self.current_workflow_id, self.user_id, building=False,
                    )
                except Exception:
                    logger.warning(
                        "Failed to clear building=False for workflow %s — "
                        "workflow may appear stuck in 'Building' state",
                        self.current_workflow_id,
                        exc_info=True,
                    )
