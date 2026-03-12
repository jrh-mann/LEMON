"""SSE-based chat task — manages a single chat turn in a background thread.

Refactored from WsChatTask: replaces ConnectionRegistry + conn_id with
EventSink. Events are pushed to a queue that FastAPI yields as SSE.

No heartbeat thread needed (HTTP keepalive handles it).
No dead connection detection needed (sink.is_closed detects client disconnect).
No conn_id locking needed (sink swap for resume is simpler).
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

from .common import utc_now
from .conversations import Conversation, ConversationStore
from .response_utils import extract_tool_calls, summarize_response
from .sse import EventSink
from .task_registry import task_registry
from .tool_summaries import ToolSummaryTracker
from ..agents.turn import Turn, TurnStatus
from ..tools.constants import WORKFLOW_EDIT_TOOLS, WORKFLOW_INPUT_TOOLS
from ..utils.cancellation import CancellationError
from ..utils.uploads import save_uploaded_file, save_annotations
from ..utils.paths import lemon_data_dir
from ..storage.conversation_log import ConversationLogger
from ..storage.workflows import WorkflowStore
from ..workflow_persistence import persist_workflow_snapshot

logger = logging.getLogger("backend.api")

# Maximum wall-clock time a single chat turn can run before being killed.
# Prevents zombie tasks from LLM hangs or tool deadlocks.
_TASK_TIMEOUT_SECONDS = 300.0


@dataclass
class ChatTask:
    """Manages a single chat turn — runs in a background thread.

    Pushes events to an EventSink which FastAPI streams as SSE.
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
    executed_tools: list[dict[str, Any]] = field(default_factory=list)
    tool_summary: ToolSummaryTracker = field(default_factory=ToolSummaryTracker)
    did_stream: bool = False
    convo: Optional[Conversation] = None
    img_annotations: Optional[list[dict[str, Any]]] = None
    saved_file_paths: list[dict[str, Any]] = field(default_factory=list)
    # Persistent audit log for the conversation lifecycle
    conversation_logger: Optional[ConversationLogger] = None
    # Accumulated thinking chunks — flushed as a single entry after respond()
    thinking_chunks: list[str] = field(default_factory=list)
    # Accumulated stream text — replayed on resume so refresh doesn't lose content
    stream_buffer: str = ""
    # Last workflow state emitted — replayed on resume so canvas syncs after refresh
    _last_workflow_state: Optional[Dict[str, Any]] = None
    # Cached cancellation flag — set by TaskRegistry.cancel()
    _cancelled: bool = False
    # Whether a chat_cancelled event has already been emitted for this task
    _notified: bool = False
    # Timestamp for stale task purging in TaskRegistry
    _created_at: float = field(default_factory=time.monotonic)

    # --- Helpers ---

    def is_cancelled(self) -> bool:
        """Check cancellation flag (fast path — no lock needed)."""
        if self._cancelled:
            return True
        # Also check if the client disconnected (SSE stream closed)
        if self.sink.is_closed:
            return True
        return False

    def _emit(self, event: str, payload: dict) -> None:
        """Push an event to the SSE stream.

        Automatically includes workflow_id so the frontend can route events
        to the correct per-workflow conversation.
        """
        if self.current_workflow_id and "workflow_id" not in payload:
            payload["workflow_id"] = self.current_workflow_id
        self.sink.push(event, payload)

    def emit_progress(self, event: str, status: str, *, tool: Optional[str] = None) -> None:
        payload: Dict[str, Any] = {"event": event, "status": status, "task_id": self.task_id}
        if tool:
            payload["tool"] = tool
        self._emit("chat_progress", payload)

    def emit_error(self, error: str) -> None:
        if self.is_cancelled():
            return
        self._emit("agent_error", {"task_id": self.task_id, "error": error})

    def emit_cancelled(self) -> None:
        if task_registry.mark_notified(self.task_id):
            self._emit("chat_cancelled", {"task_id": self.task_id})

    def stream_chunk(self, chunk: str) -> None:
        """Stream an SDK chunk to the frontend as-is (no char-by-char splitting).

        The Anthropic SDK already yields ~20-50 char chunks. Emitting them
        directly removes the 5ms-per-char artificial delay. If a typewriter
        effect is desired, it should be done client-side with CSS animation.
        """
        if self.is_cancelled():
            return
        self.did_stream = True
        self.stream_buffer += chunk  # Accumulate for resume replay
        self._emit("chat_stream", {"chunk": chunk, "task_id": self.task_id})

    def stream_thinking(self, chunk: str) -> None:
        """Stream LLM reasoning/thinking chunks to the frontend."""
        if not chunk or self.is_cancelled():
            return
        self.thinking_chunks.append(chunk)
        self._emit("chat_thinking", {"chunk": chunk, "task_id": self.task_id})

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
        summary = self.tool_summary.flush()
        if summary:
            self.stream_chunk(summary)

    def swap_sink(self, new_sink: EventSink) -> None:
        """Swap the event sink for resume after page refresh.

        Replays accumulated thinking + stream content to the new sink,
        then routes all future events through it. Closes the old sink
        to end the old SSE stream.
        """
        # Send a progress event so the frontend knows it's reconnected
        new_sink.push("chat_progress", {
            "event": "resumed",
            "status": "Processing...",
            "task_id": self.task_id,
            "workflow_id": self.current_workflow_id or "",
        })
        # Replay accumulated thinking
        if self.thinking_chunks:
            new_sink.push("chat_thinking", {
                "chunk": "".join(self.thinking_chunks),
                "task_id": self.task_id,
                "workflow_id": self.current_workflow_id or "",
            })
        # Replay accumulated stream content
        if self.stream_buffer:
            new_sink.push("chat_stream", {
                "chunk": self.stream_buffer,
                "task_id": self.task_id,
                "workflow_id": self.current_workflow_id or "",
            })
        # Replay last workflow state so the canvas syncs
        if self._last_workflow_state:
            new_sink.push("workflow_state_updated", {
                **self._last_workflow_state,
                "workflow_id": self.current_workflow_id or "",
            })
        # Swap: close old sink, install new one
        old_sink = self.sink
        self.sink = new_sink
        old_sink.close()

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
        """Dispatch tool lifecycle events: start, complete, batch_complete.

        Records tool results and emits SSE events so the frontend can
        update the canvas in real time.
        """
        cancelled = self.is_cancelled()

        if event == "tool_start":
            entry: Dict[str, Any] = {"tool": tool, "arguments": args}
            if cancelled:
                entry["interrupted"] = True
            self.executed_tools.append(entry)
            # Real-time progress so the user sees which tool is running
            if not cancelled:
                self.emit_progress("tool_start", f"Running {tool}...", tool=tool)
        if event == "tool_complete":
            if isinstance(result, dict) and result.get("skipped"):
                return
            success = True
            if isinstance(result, dict) and "success" in result:
                success = bool(result.get("success"))
            self.tool_summary.note(tool, success=success)
            for executed in reversed(self.executed_tools):
                if executed.get("tool") == tool and "result" not in executed:
                    executed["result"] = result
                    executed["success"] = success
                    if cancelled:
                        executed["interrupted"] = True
                    break
            # Snapshot workflow after successful edit tool calls
            if success and tool in WORKFLOW_EDIT_TOOLS and self.conversation_logger and self.convo:
                try:
                    self.conversation_logger.log_workflow_snapshot(
                        self.convo.id,
                        self.convo.orchestrator.current_workflow,
                        task_id=self.task_id,
                    )
                except Exception:
                    logger.error(
                        "Failed to log workflow snapshot: tool=%s conv=%s",
                        tool, self.convo.id if self.convo else "?",
                        exc_info=True,
                    )
        if event == "tool_batch_complete":
            self.flush_tool_summary()

        # Skip emissions when cancelled
        if cancelled:
            return

        if tool == "update_plan" and event == "tool_complete" and isinstance(result, dict):
            self._emit("plan_updated", {"items": result.get("items", [])})

        if tool == "ask_question" and event == "tool_complete" and isinstance(result, dict) and result.get("success"):
            questions = result.get("questions", [])
            for q in questions:
                self._emit("pending_question", {
                    "question": q.get("question", ""),
                    "options": q.get("options", []),
                })

        if event == "tool_complete" and isinstance(result, dict) and result.get("success"):
            payload = self._workflow_state_payload()

            if tool in WORKFLOW_EDIT_TOOLS:
                action = result.get("action")
                logger.info(
                    "Emitting workflow_update action=%s tool=%s workflow_id=%s",
                    action, tool, result.get("workflow_id"),
                )
                self._emit("workflow_update", {"action": action, "data": result})
                if payload:
                    self._emit("workflow_state_updated", payload)
                    self._last_workflow_state = payload

                has_new_vars = isinstance(result.get("new_variables"), list) and result["new_variables"]
                has_removed_vars = isinstance(result.get("removed_variable_ids"), list) and result["removed_variable_ids"]
                if (has_new_vars or has_removed_vars) and self.convo:
                    self._emit("analysis_updated", {
                        "variables": self.convo.orchestrator.workflow_analysis.get("variables", []),
                        "outputs": self.convo.orchestrator.workflow_analysis.get("outputs", []),
                        "task_id": self.task_id,
                    })

            if tool in WORKFLOW_INPUT_TOOLS and payload:
                self._emit("workflow_state_updated", payload)
                self._last_workflow_state = payload
                self._emit("analysis_updated", {
                    "variables": self.convo.orchestrator.workflow_analysis.get("variables", []),
                    "outputs": self.convo.orchestrator.workflow_analysis.get("outputs", []),
                    "task_id": self.task_id,
                })

            if tool == "save_workflow_to_library":
                self._emit("workflow_saved", {
                    "workflow_id": result.get("workflow_id"),
                    "name": result.get("name"),
                    "is_draft": False,
                    "already_saved": result.get("already_saved", False),
                })

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
        # Pass the EventSink so background builders (create_subworkflow, update_subworkflow)
        # can emit events on the parent chat's SSE stream.
        self.convo.orchestrator.event_sink = self.sink
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
        """Execute one chat turn: save files, sync state, call LLM, emit response.

        Creates a Turn object that centralizes audit logging and history
        persistence. The Turn's commit() is the single point where
        ConversationManager.history is mutated.
        """
        self.emit_progress("start", "Thinking...")
        threading.Thread(target=self._timeout_watchdog, daemon=True).start()

        turn: Optional[Turn] = None
        response_text = ""

        try:
            self.convo = self.conversation_store.get_or_create(self.conversation_id)
            if not self._save_uploaded_files():
                return
            self._sync_payload_workflow()
            self._sync_orchestrator_from_convo()
            self._persist_conversation_metadata()

            # Create Turn — centralizes audit logging + history persistence
            turn = Turn(
                self.message, self.convo.id,
                conversation_logger=self.conversation_logger,
                task_id=self.task_id,
            )
            # Ensure conversation row exists in audit DB before Turn.start()
            if self.conversation_logger:
                try:
                    self.conversation_logger.ensure_conversation(
                        self.convo.id,
                        user_id=self.user_id,
                        workflow_id=self.current_workflow_id,
                        model="claude-sonnet-4-6",
                    )
                except Exception:
                    logger.error(
                        "Failed to ensure conversation in audit DB: conv=%s",
                        self.convo.id, exc_info=True,
                    )

            # File metadata for audit log
            file_meta = [
                {"name": f.get("name"), "file_type": f.get("file_type")}
                for f in self.saved_file_paths
            ] if self.saved_file_paths else None
            turn.start(file_meta=file_meta)

            response_text = self.convo.orchestrator.respond(
                self.message,
                turn=turn,
                has_files=self.saved_file_paths if self.saved_file_paths else [],
                stream=self.stream_chunk,
                allow_tools=True,
                should_cancel=self.is_cancelled,
                on_tool_event=self.on_tool_event,
                thinking=True,
                on_thinking=self.stream_thinking,
            )

            # Turn completed successfully
            orch = self.convo.orchestrator
            turn.complete(
                response_text,
                input_tokens=orch.conversation._last_input_tokens or 0,
                output_tokens=getattr(orch, "_last_output_tokens", None) or 0,
            )
            turn.commit(orch.conversation)
            self._log_thinking()
            self._sync_convo_from_orchestrator()

            # Emit context window usage so the frontend can show an indicator
            self._emit("context_status", {
                "usage_pct": orch.conversation.context_usage_pct,
                "input_tokens": orch.conversation._last_input_tokens,
                "message_count": len(orch.conversation.history),
            })
            self._emit_response(response_text)

        except CancellationError:
            if turn and turn.status not in (TurnStatus.COMPLETED, TurnStatus.CANCELLED, TurnStatus.FAILED):
                turn.cancel([self.stream_buffer] if self.stream_buffer else [])
                turn.commit(self.convo.orchestrator.conversation)
            response_text = turn.partial_text if turn else ""
            self._emit_response(response_text, cancelled=True)
            self.emit_cancelled()

        except Exception as exc:
            logger.exception("Chat task failed: task=%s", self.task_id)
            if turn and turn.status not in (TurnStatus.COMPLETED, TurnStatus.CANCELLED, TurnStatus.FAILED):
                turn.fail(str(exc))
                if self.convo:
                    turn.commit(self.convo.orchestrator.conversation)
            if isinstance(exc, anthropic.RateLimitError):
                self._emit("agent_error", {
                    "task_id": self.task_id,
                    "error": str(exc),
                    "transient": True,
                })
            else:
                self.emit_error(f"Something went wrong: {type(exc).__name__}. Please try again.")

        finally:
            self.done.set()
            task_registry.unregister(self)
            # Close the SSE stream
            self.sink.close()
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
