"""Socket.IO chat workflow for the API server.

Background threads use registry.send_to_sync(sid, event, payload) to emit
events via the python-socketio AsyncServer. The conn_id parameter throughout
this module is the Socket.IO session ID (sid).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock
from typing import Any, Dict, Optional
from uuid import uuid4

from .common import utc_now
from .conversations import Conversation, ConversationStore
from .response_utils import extract_tool_calls, summarize_response
from .tool_summaries import ToolSummaryTracker
from .ws_registry import ConnectionRegistry
from ..tools.constants import WORKFLOW_EDIT_TOOLS, WORKFLOW_INPUT_TOOLS
from ..utils.uploads import save_uploaded_file, save_annotations
from ..utils.paths import lemon_data_dir
from ..storage.conversation_log import ConversationLogger
from ..storage.workflows import WorkflowStore
from ..workflow_persistence import persist_workflow_snapshot

logger = logging.getLogger("backend.api")

# ---------- Unified task registry ----------
# Single registry replacing the old dual-dict system (_TASK_STATE + _ACTIVE_TASKS).
# Indexes tasks by task_id (primary) and (user_id, workflow_id) (for resume).
# Cancellation and notification state live directly on WsChatTask instances.

class TaskRegistry:
    """Single source of truth for all in-progress chat tasks."""

    _TTL_SECONDS = 1800.0

    def __init__(self) -> None:
        self._lock = Lock()
        self._by_task_id: Dict[str, "WsChatTask"] = {}
        self._by_workflow: Dict[tuple[str, str], "WsChatTask"] = {}

    def register(self, task: "WsChatTask") -> None:
        """Register a task. Purges stale entries on each registration."""
        with self._lock:
            self._purge_stale()
            self._by_task_id[task.task_id] = task
            if task.current_workflow_id:
                self._by_workflow[(task.user_id, task.current_workflow_id)] = task

    def cancel(self, task_id: str) -> Optional["WsChatTask"]:
        """Mark a task as cancelled. Returns the task if found."""
        with self._lock:
            task = self._by_task_id.get(task_id)
            if task:
                task._cancelled = True
            return task

    def mark_notified(self, task_id: str) -> bool:
        """Mark cancellation as notified. Returns True on first call only."""
        with self._lock:
            task = self._by_task_id.get(task_id)
            if not task or task._notified:
                return False
            task._notified = True
            return True

    def get_by_workflow(self, user_id: str, workflow_id: str) -> Optional["WsChatTask"]:
        with self._lock:
            return self._by_workflow.get((user_id, workflow_id))

    def unregister(self, task: "WsChatTask") -> None:
        with self._lock:
            self._by_task_id.pop(task.task_id, None)
            if task.current_workflow_id:
                self._by_workflow.pop((task.user_id, task.current_workflow_id), None)

    def _purge_stale(self) -> None:
        now = time.monotonic()
        stale = [
            tid for tid, t in self._by_task_id.items()
            if now - t._created_at > self._TTL_SECONDS
        ]
        for tid in stale:
            task = self._by_task_id.pop(tid, None)
            if task and task.current_workflow_id:
                self._by_workflow.pop((task.user_id, task.current_workflow_id), None)


_task_registry = TaskRegistry()


# ---------- Chat task ----------

@dataclass
class WsChatTask:
    """Manages a single chat turn — runs in a background thread."""

    registry: ConnectionRegistry
    conversation_store: ConversationStore
    repo_root: Path
    workflow_store: WorkflowStore
    user_id: str
    conn_id: str
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
    # Accumulated stream text — replayed on resume_task so refresh doesn't lose content
    stream_buffer: str = ""
    # Tool start times for duration measurement (keyed by tool name)
    _tool_start_times: dict[str, float] = field(default_factory=dict)
    # Cached cancellation flag — set by TaskRegistry.cancel() to avoid
    # lock + dict lookup on every stream chunk. Volatile read is safe
    # because Python's GIL makes bool assignment atomic.
    _cancelled: bool = False
    # Whether a chat_cancelled event has already been emitted for this task.
    # Prevents duplicate cancellation notifications from concurrent paths.
    _notified: bool = False
    # Timestamp for stale task purging in TaskRegistry.
    _created_at: float = field(default_factory=time.monotonic)
    # Lock protecting conn_id reads/writes between the background thread
    # (_emit) and handle_resume_task which mutates conn_id.
    _conn_lock: Lock = field(default_factory=Lock)
    # Consecutive send failures — tracks dead connections.
    _consecutive_send_failures: int = 0
    # Monotonic timestamp of the first failure in the current streak.
    # Connection is declared dead only after failures span DEAD_CONN_GRACE_SECONDS,
    # giving time for page refreshes to reconnect via resume_task.
    _first_failure_time: Optional[float] = None

    # --- Helpers ---

    def is_cancelled(self) -> bool:
        # Fast path: cached flag (set by handle_cancel_task or dead-connection detection)
        return self._cancelled

    def _emit(self, event: str, payload: dict) -> None:
        """Emit a JSON message via the registry (sync, from background thread).

        Automatically includes workflow_id so the frontend can route events
        to the correct per-workflow conversation. Tracks consecutive failures
        and cancels the task if the connection appears dead.
        """
        if self.current_workflow_id and "workflow_id" not in payload:
            payload["workflow_id"] = self.current_workflow_id
        # Read conn_id under lock — handle_resume_task may be writing it
        with self._conn_lock:
            sid = self.conn_id
        ok = self.registry.send_to_sync(sid, event, payload)
        if ok:
            self._consecutive_send_failures = 0
            self._first_failure_time = None
        else:
            self._consecutive_send_failures += 1
            now = time.monotonic()
            if self._first_failure_time is None:
                self._first_failure_time = now
            # Declare dead only after failures span 10+ seconds — gives page
            # refreshes enough time to reconnect via resume_task.
            elif now - self._first_failure_time > 10.0:
                logger.warning(
                    "Dead connection detected (%d failures over %.1fs) — aborting task %s",
                    self._consecutive_send_failures,
                    now - self._first_failure_time,
                    self.task_id,
                )
                self._cancelled = True

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
        if _task_registry.mark_notified(self.task_id):
            self._emit("chat_cancelled", {"task_id": self.task_id})

    def stream_chunk(self, chunk: str) -> None:
        """Stream an SDK chunk to the frontend as-is (no char-by-char splitting).

        The Anthropic SDK already yields ~20-50 char chunks. Emitting them
        directly removes the 5ms-per-char artificial delay that made a 4000-char
        response take 20+ seconds. If a typewriter effect is desired, it should
        be done client-side with CSS animation.
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

    def heartbeat(self) -> None:
        while not self.done.is_set():
            # done.wait() returns immediately when done is set, unlike sleep()
            # which hangs for the full duration even after the task finishes.
            self.done.wait(5)
            if self.done.is_set() or self.is_cancelled():
                break
            self.emit_progress("heartbeat", "Analysing...")

    def flush_tool_summary(self) -> None:
        summary = self.tool_summary.flush()
        if summary:
            self.stream_chunk(summary)

    def _workflow_state_payload(self) -> Optional[Dict[str, Any]]:
        """Build workflow state payload from current conversation.

        Returns a dict with workflow_id, workflow, analysis, and task_id,
        or None when no conversation is available.
        """
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

        Records tool results, logs to the audit trail, and emits socket
        events so the frontend can update the canvas in real time.
        """
        cancelled = self.is_cancelled()

        if event == "tool_start":
            entry: Dict[str, Any] = {"tool": tool, "arguments": args}
            if cancelled:
                entry["interrupted"] = True
            self.executed_tools.append(entry)
            # Record start time for duration measurement
            self._tool_start_times[tool] = time.perf_counter()
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
            # Log tool call to the audit trail
            if self.conversation_logger and self.convo:
                start = self._tool_start_times.pop(tool, None)
                duration_ms = (time.perf_counter() - start) * 1000 if start else 0.0
                try:
                    self.conversation_logger.log_tool_call(
                        self.convo.id, tool, args, result, success, duration_ms,
                        task_id=self.task_id,
                    )
                    # Snapshot workflow after successful edit tool calls
                    if success and tool in WORKFLOW_EDIT_TOOLS and self.convo:
                        self.conversation_logger.log_workflow_snapshot(
                            self.convo.id,
                            self.convo.orchestrator.current_workflow,
                            task_id=self.task_id,
                        )
                except Exception:
                    logger.error(
                        "Failed to log tool call to audit trail: tool=%s conv=%s",
                        tool, self.convo.id if self.convo else "?",
                        exc_info=True,
                    )
        if event == "tool_batch_complete":
            self.flush_tool_summary()

        # Skip socket emissions when cancelled
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
        """Persist the canvas workflow snapshot to the database.

        Creates or updates the workflow record and emits a workflow_created
        event if this is the first time the workflow is saved. Also looks
        up the workflow name from the DB for system prompt display.
        """
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
        """Synchronise orchestrator state from the conversation object.

        Wires up workflow state, analysis, stores, and connection info
        so the orchestrator can operate on the current canvas. Also
        persists the workflow snapshot via _ensure_workflow_persisted().
        """
        if not self.convo:
            return
        self.convo.orchestrator.sync_workflow(lambda: self.convo.workflow_state)
        self.convo.orchestrator.sync_workflow_analysis(lambda: self.convo.workflow_analysis)
        self.convo.orchestrator.workflow_store = self.workflow_store
        self.convo.orchestrator.user_id = self.user_id
        self.convo.orchestrator.repo_root = self.repo_root
        # Pass ws_registry + conn_id for background subworkflow builders
        self.convo.orchestrator.ws_registry = self.registry
        self.convo.orchestrator.conn_id = self.conn_id
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
        summary = summarize_response(response_text) if tool_calls else ""
        if self.convo:
            self.convo.updated_at = utc_now()
        # Determine the response field: if streamed, chunks were already sent
        # so the response field is "". Otherwise use the full text.
        response_field = summary if tool_calls else ("" if self.did_stream else response_text)
        # Log empty non-streamed responses as warnings for debugging
        if not response_field and not self.did_stream and not cancelled:
            logger.warning(
                "Emitting empty chat_response (no stream, no text, no tools) "
                "task=%s conn=%s", self.task_id, self.conn_id,
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
    # These are wrapped in try/except because a logging failure should
    # never crash the chat, but errors are logged with exc_info=True
    # so they remain visible per CLAUDE.md "fail loudly" convention.

    def _log_user_message(self) -> None:
        """Log user message to audit trail."""
        if not (self.conversation_logger and self.convo):
            logger.warning(
                "Audit log skipped: conversation_logger=%s convo=%s",
                self.conversation_logger is not None, self.convo is not None,
            )
            return
        try:
            self.conversation_logger.ensure_conversation(
                self.convo.id,
                user_id=self.user_id,
                workflow_id=self.current_workflow_id,
                model="claude-sonnet-4-6",
            )
            file_meta = [
                {"name": f.get("name"), "file_type": f.get("file_type")}
                for f in self.saved_file_paths
            ] if self.saved_file_paths else None
            self.conversation_logger.log_user_message(
                self.convo.id, self.message, files=file_meta, task_id=self.task_id,
            )
            logger.info(
                "Audit log: recorded user message conv=%s task=%s",
                self.convo.id, self.task_id,
            )
        except Exception:
            logger.error(
                "Failed to log user message to audit trail: conv=%s task=%s",
                self.convo.id, self.task_id,
                exc_info=True,
            )

    def _log_assistant_response(self, response_text: str) -> None:
        """Log assistant response and thinking to audit trail."""
        if not (self.conversation_logger and self.convo):
            return
        try:
            orch = self.convo.orchestrator
            self.conversation_logger.log_assistant_response(
                self.convo.id, response_text,
                input_tokens=orch.conversation._last_input_tokens or None,
                output_tokens=getattr(orch, "_last_output_tokens", None),
                task_id=self.task_id,
            )
            if self.thinking_chunks:
                self.conversation_logger.log_thinking(
                    self.convo.id, "".join(self.thinking_chunks), task_id=self.task_id,
                )
        except Exception:
            logger.error(
                "Failed to log assistant response to audit trail: conv=%s task=%s",
                self.convo.id, self.task_id,
                exc_info=True,
            )

    def _log_error(self, exc: Exception) -> None:
        """Log an error to the audit trail."""
        if not (self.conversation_logger and self.convo):
            return
        try:
            self.conversation_logger.log_error(
                self.convo.id, exc, task_id=self.task_id,
            )
        except Exception:
            logger.warning("Failed to log error to audit trail", exc_info=True)

    # --- Conversation metadata persistence ---

    def _persist_conversation_metadata(self) -> None:
        """Persist conversation_id and uploaded file metadata on the workflow.

        Stores these on the workflow record so the chat session and any
        uploaded images survive page reloads.
        """
        if not (self.current_workflow_id and self.workflow_store and self.convo):
            return
        try:
            update_kwargs: Dict[str, Any] = {"conversation_id": self.convo.id}
            # Store uploaded file metadata so images reappear after refresh
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
        """Execute one chat turn: save files, sync state, call LLM, emit response."""
        self.emit_progress("start", "Thinking...")
        threading.Thread(target=self.heartbeat, daemon=True).start()

        # NOTE: TaskRegistry registration and building=True are set in
        # handle_ws_chat BEFORE the thread spawns (eliminates race condition
        # where a fast page refresh misses in-progress state).

        try:
            self.convo = self.conversation_store.get_or_create(self.conversation_id)
            if not self._save_uploaded_files():
                return
            self._sync_payload_workflow()
            self._sync_orchestrator_from_convo()
            self._persist_conversation_metadata()
            self._log_user_message()

            response_text = self.convo.orchestrator.respond(
                self.message,
                has_files=self.saved_file_paths if self.saved_file_paths else [],
                stream=self.stream_chunk,
                allow_tools=True,
                should_cancel=self.is_cancelled,
                on_tool_event=self.on_tool_event,
                thinking_budget=50_000,
                on_thinking=self.stream_thinking,
            )
            self._sync_convo_from_orchestrator()
            self._log_assistant_response(response_text)

            # Emit context window usage so the frontend can show an indicator
            orch = self.convo.orchestrator
            self._emit("context_status", {
                "usage_pct": orch.conversation.context_usage_pct,
                "input_tokens": orch.conversation._last_input_tokens,
                "message_count": len(orch.conversation.history),
            })
            if self.is_cancelled():
                self._emit_response(response_text, cancelled=True)
                self.emit_cancelled()
                return
            self._emit_response(response_text)
        except Exception as exc:
            logger.exception("WS chat failed: task=%s", self.task_id)
            self._log_error(exc)
            self.emit_error(str(exc))
        finally:
            self.done.set()
            _task_registry.unregister(self)
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


# ---------- Handler functions (called from ws_handler.py dispatch loop) ----------

def handle_ws_chat(
    registry: ConnectionRegistry,
    *,
    conn_id: str,
    conversation_store: ConversationStore,
    repo_root: Path,
    workflow_store: Any,
    user_id: str,
    payload: Dict[str, Any],
    conversation_logger: Optional[ConversationLogger] = None,
) -> None:
    """Handle incoming chat message — spawn background task."""
    message = payload.get("message", "")
    task_id = payload.get("task_id")

    raw_files = payload.get("files")
    logger.info(
        "handle_ws_chat: message_len=%d files_present=%s files_count=%d",
        len(message) if isinstance(message, str) else 0,
        raw_files is not None,
        len(raw_files) if isinstance(raw_files, list) else 0,
    )

    if not isinstance(message, str) or not message.strip():
        registry.send_to_sync(conn_id, "agent_error", {"task_id": task_id, "error": "message is required"})
        return

    if not isinstance(task_id, str) or not task_id.strip():
        task_id = uuid4().hex

    current_workflow_id = payload.get("current_workflow_id") or f"wf_{uuid4().hex}"

    task = WsChatTask(
        registry=registry,
        conversation_store=conversation_store,
        repo_root=repo_root,
        workflow_store=workflow_store,
        user_id=user_id,
        conn_id=conn_id,
        task_id=task_id,
        message=message,
        conversation_id=payload.get("conversation_id"),
        files_data=payload.get("files") or [],
        workflow=payload.get("workflow"),
        analysis=payload.get("analysis"),
        current_workflow_id=current_workflow_id,
        open_tabs=payload.get("open_tabs"),
        img_annotations=payload.get("annotations"),
        conversation_logger=conversation_logger,
    )

    # Register and set building=True BEFORE spawning the thread.
    # This eliminates the race where a page refresh between thread spawn
    # and thread execution finds building=false and no active task.
    _task_registry.register(task)
    if workflow_store and current_workflow_id:
        try:
            # Ensure the workflow row exists — for brand-new unsaved workflows,
            # the DB row doesn't exist yet, so UPDATE building=True would be a no-op.
            # persist_workflow_snapshot does create-or-update.
            workflow_data = payload.get("workflow") or {}
            persist_workflow_snapshot(
                workflow_store,
                workflow_id=current_workflow_id,
                user_id=user_id,
                name="New Workflow",
                description="",
                nodes=workflow_data.get("nodes", []),
                edges=workflow_data.get("edges", []),
                variables=workflow_data.get("variables", []),
                outputs=workflow_data.get("outputs"),
                output_type=workflow_data.get("output_type"),
                is_draft=True,
            )
            workflow_store.update_workflow(current_workflow_id, user_id, building=True)
        except Exception:
            logger.error("Failed to set building=True for %s before thread spawn", current_workflow_id, exc_info=True)

    threading.Thread(target=task.run, daemon=True, name=f"ws-chat-{task_id}").start()


def handle_cancel_task(
    registry: ConnectionRegistry,
    *,
    conn_id: str,
    payload: Dict[str, Any],
) -> None:
    """Handle cancel_task message.

    Sets _cancelled on the WsChatTask via the unified registry so
    is_cancelled() returns True immediately (no lock on hot path).
    """
    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        return
    _task_registry.cancel(task_id)
    if _task_registry.mark_notified(task_id):
        registry.send_to_sync(conn_id, "chat_cancelled", {"task_id": task_id})


def handle_sync_workflow(
    registry: ConnectionRegistry,
    *,
    conversation_store: ConversationStore,
    payload: Dict[str, Any],
) -> None:
    """Handle full workflow sync from frontend (fire-and-forget)."""
    conversation_id = payload.get("conversation_id")
    workflow = payload.get("workflow")
    source = payload.get("source", "unknown")

    if not conversation_id:
        logger.warning("sync_workflow missing conversation_id")
        return
    if not isinstance(workflow, dict):
        logger.warning("sync_workflow invalid workflow format")
        return

    convo = conversation_store.get_or_create(conversation_id)
    convo.update_workflow_state(workflow)

    analysis = payload.get("analysis")
    if isinstance(analysis, dict):
        convo.update_workflow_analysis(analysis)

    logger.info(
        "Synced workflow conv=%s source=%s nodes=%d edges=%d",
        conversation_id, source,
        len(workflow.get("nodes", [])),
        len(workflow.get("edges", [])),
    )


def handle_resume_task(
    registry: ConnectionRegistry,
    *,
    conn_id: str,
    user_id: str,
    payload: Dict[str, Any],
) -> None:
    """Reconnect a refreshed frontend to a still-running backend task.

    The frontend sends this after loading a workflow with building=true.
    We look up the active task and update its conn_id so future events
    (streaming, tool calls, workflow updates) reach the new WebSocket.
    """
    workflow_id = payload.get("workflow_id")
    if not workflow_id:
        return

    task = _task_registry.get_by_workflow(user_id, workflow_id)

    if task and not task.done.is_set():
        # Lock conn_id mutation — the background thread reads it in _emit()
        with task._conn_lock:
            old_conn_id = task.conn_id
            task.conn_id = conn_id
        # Reset failure counter since we have a fresh connection
        task._consecutive_send_failures = 0
        # Snapshot accumulated content after switching conn_id so we
        # capture everything streamed up to this point.
        replay_thinking = "".join(task.thinking_chunks)
        replay_stream = task.stream_buffer
        logger.info(
            "resume_task: reconnected workflow=%s old_conn=%s new_conn=%s "
            "replay_thinking=%d replay_stream=%d",
            workflow_id, old_conn_id, conn_id,
            len(replay_thinking), len(replay_stream),
        )
        # Send an immediate progress event so the frontend knows it's connected
        registry.send_to_sync(conn_id, "chat_progress", {
            "event": "resumed",
            "status": "Processing...",
            "task_id": task.task_id,
            "workflow_id": workflow_id,
        })
        # Replay accumulated thinking and stream content so the frontend
        # restores everything that was displayed before the refresh.
        if replay_thinking:
            registry.send_to_sync(conn_id, "chat_thinking", {
                "chunk": replay_thinking,
                "task_id": task.task_id,
                "workflow_id": workflow_id,
            })
        if replay_stream:
            registry.send_to_sync(conn_id, "chat_stream", {
                "chunk": replay_stream,
                "task_id": task.task_id,
                "workflow_id": workflow_id,
            })
    else:
        # Task already finished — tell the frontend to clear streaming state
        # and re-fetch conversation history for the final response.
        logger.info("resume_task: no active task for workflow=%s, sending task_finished", workflow_id)
        registry.send_to_sync(conn_id, "task_finished", {
            "workflow_id": workflow_id,
        })
