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
from uuid import uuid4

import anthropic

from .chat_event_channel import ChatEventChannel
from .chat_turn_runner import ChatRuntimePorts, TurnResult, run_turn
from .common import utc_now
from .conversations import Conversation, ConversationStore
from .response_utils import extract_tool_calls
from .sse import EventSink
from .task_registry import task_registry
from .tool_event_projector import ToolEventProjector
from ..agents.turn import TurnStatus
from ..utils.uploads import save_uploaded_file, save_annotations
from ..utils.paths import lemon_data_dir
from ..storage.conversation_log import ConversationLogger
from ..storage.workflows import WorkflowStore
from ..workflow_persistence import persist_workflow_snapshot

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

    # --- File handling ---

    def _save_uploaded_files(self) -> bool:
        """Save all uploaded files to disk and populate self.saved_file_paths."""
        logger.info("_save_uploaded_files: files_data count=%d", len(self.files_data))
        if not self.files_data:
            return True
        for file_info in self.files_data:
            data_url = file_info.get("data_url", "")
            logger.info(
                "_save_uploaded_files: processing file id=%s name=%s data_url_len=%d",
                file_info.get("id", "?"), file_info.get("name", "?"),
                len(data_url) if isinstance(data_url, str) else 0,
            )
            if not isinstance(data_url, str) or not data_url.strip():
                logger.warning("_save_uploaded_files: skipping file with empty data_url: %s", file_info.get("name"))
                continue
            try:
                rel_path, file_type = save_uploaded_file(data_url, repo_root=self.repo_root)
                abs_path = str(lemon_data_dir(self.repo_root) / rel_path)
                self.saved_file_paths.append({
                    "id": file_info.get("id", ""),
                    "name": file_info.get("name", ""),
                    "path": abs_path,
                    "file_type": file_type,
                    "purpose": file_info.get("purpose", "unclassified"),
                })
            except Exception as exc:
                logger.exception("Failed to save uploaded file: %s", file_info.get("name"))
                self.emit_error(f"Invalid file '{file_info.get('name', '?')}': {exc}")
                return False
        if self.img_annotations and isinstance(self.img_annotations, list) and self.saved_file_paths:
            first_image = next(
                (f for f in self.saved_file_paths if f["file_type"] == "image"), None
            )
            if first_image:
                save_annotations(first_image["path"], self.img_annotations, repo_root=self.repo_root)
        return True

    # --- Workflow sync ---

    def _sync_payload_workflow(self) -> None:
        if not self.convo:
            return
        if isinstance(self.workflow, dict):
            self.convo.update_workflow_state(self.workflow)
        if isinstance(self.analysis, dict):
            self.convo.update_workflow_analysis(self.analysis)

    def _ensure_workflow_persisted(self) -> None:
        """Persist the canvas workflow snapshot to the database."""
        if not (self.convo and self.current_workflow_id and self.workflow_store):
            return
        workflow = self.convo.workflow
        try:
            created, persisted = persist_workflow_snapshot(
                self.workflow_store,
                workflow_id=self.current_workflow_id,
                user_id=self.user_id,
                name="New Workflow",
                description="",
                nodes=workflow.get("nodes", []),
                edges=workflow.get("edges", []),
                variables=workflow.get("variables", []),
                outputs=workflow.get("outputs", []),
                output_type=workflow.get("output_type", "string"),
                is_draft=True,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to persist canvas workflow {self.current_workflow_id}: {exc}"
            ) from exc

        self.convo.workflow["outputs"] = persisted["outputs"]
        self.convo.workflow["output_type"] = persisted["output_type"]
        logger.info(
            "Persisted canvas workflow snapshot %s for user %s",
            self.current_workflow_id, self.user_id,
        )
        if created:
            self._emit("workflow_created", {
                "workflow_id": self.current_workflow_id,
                "name": "New Workflow",
                "output_type": persisted["output_type"],
                "is_draft": True,
            })
        self.convo.orchestrator.current_workflow_id = self.current_workflow_id
        # Look up workflow name from DB for system prompt display
        record = self.workflow_store.get_workflow(self.current_workflow_id, self.user_id)
        if record:
            self.convo.orchestrator.current_workflow_name = record.name

    def _sync_orchestrator_from_convo(self) -> None:
        """Synchronise orchestrator state from the conversation object."""
        if not self.convo:
            return
        self.convo.orchestrator.sync_workflow(lambda: self.convo.workflow_state)
        self.convo.orchestrator.sync_workflow_analysis(lambda: self.convo.workflow_analysis)
        self.convo.orchestrator.workflow_store = self.workflow_store
        self.convo.orchestrator.user_id = self.user_id
        self.convo.orchestrator.repo_root = self.repo_root
        # Pass the EventSink so subworkflow tools can push fire-and-forget
        # notifications (subworkflow_created, subworkflow_ready) to the
        # parent's SSE stream. Builders create their own independent sinks.
        self.convo.orchestrator.event_sink = self.channel.sink
        # Ensure the canvas workflow snapshot exists in the database
        self._ensure_workflow_persisted()
        self.convo.orchestrator.open_tabs = self.open_tabs or []
        # Inject conversation logger so the orchestrator can log compaction events
        self.convo.orchestrator.conversation._conversation_logger = self.conversation_logger
        self.convo.orchestrator.conversation._conversation_id = self.convo.id

    def _sync_convo_from_orchestrator(self) -> None:
        if not self.convo:
            return
        self.convo.update_workflow_state(self.convo.orchestrator.current_workflow)
        self.convo.update_workflow_analysis(self.convo.orchestrator.workflow_analysis)

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

    # --- Conversation metadata persistence ---

    def _persist_conversation_metadata(self) -> None:
        """Persist conversation_id and uploaded file metadata on the workflow."""
        if not (self.current_workflow_id and self.workflow_store and self.convo):
            return
        try:
            update_kwargs: Dict[str, Any] = {"conversation_id": self.convo.id}
            if self.saved_file_paths:
                data_dir = lemon_data_dir(self.repo_root)
                uploaded_files = []
                for fp in self.saved_file_paths:
                    abs_p = Path(fp["path"])
                    try:
                        rel = str(abs_p.relative_to(data_dir))
                    except ValueError:
                        rel = fp["path"]
                    uploaded_files.append({
                        "name": fp.get("name", ""),
                        "rel_path": rel,
                        "file_type": fp.get("file_type", "image"),
                        "purpose": fp.get("purpose", "unclassified"),
                    })
                update_kwargs["uploaded_files"] = uploaded_files
            self.workflow_store.update_workflow(
                self.current_workflow_id, self.user_id, **update_kwargs,
            )
        except Exception:
            logger.warning(
                "Failed to persist conversation_id/files on workflow %s — "
                "chat may not survive page refresh",
                self.current_workflow_id,
                exc_info=True,
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
