"""WebSocket chat workflow for the API server.

Replaces socket_chat.py — uses ConnectionRegistry + conn_id instead of
SocketIO + sid. Background threads use registry.send_to_sync() to emit
events to the async WebSocket.
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

logger = logging.getLogger("backend.api")

# ---------- Active task registry ----------
# Maps (user_id, workflow_id) → WsChatTask for in-progress tasks.
# Used by resume_task to reconnect a refreshed frontend to a running backend task.
_ACTIVE_TASKS: Dict[tuple[str, str], "WsChatTask"] = {}
_ACTIVE_TASKS_LOCK = Lock()

# ---------- Task cancellation state ----------

_TASK_STATE: Dict[str, Dict[str, Dict[str, Any]]] = {}
_TASK_LOCK = Lock()
_TASK_TTL_SECONDS = 1800.0


def _purge_stale_tasks_locked(now: float) -> None:
    stale_sessions: list[str] = []
    for conn_id, tasks in _TASK_STATE.items():
        stale_tasks = [
            task_id
            for task_id, state in tasks.items()
            if now - state.get("created_at", now) > _TASK_TTL_SECONDS
        ]
        for task_id in stale_tasks:
            tasks.pop(task_id, None)
        if not tasks:
            stale_sessions.append(conn_id)
    for conn_id in stale_sessions:
        _TASK_STATE.pop(conn_id, None)


def _register_task(conn_id: str, task_id: str) -> None:
    with _TASK_LOCK:
        now = time.monotonic()
        _purge_stale_tasks_locked(now)
        session_tasks = _TASK_STATE.setdefault(conn_id, {})
        session_tasks.setdefault(
            task_id,
            {"cancelled": False, "notified": False, "created_at": now},
        )


def _cancel_task(conn_id: str, task_id: str) -> None:
    with _TASK_LOCK:
        now = time.monotonic()
        _purge_stale_tasks_locked(now)
        session_tasks = _TASK_STATE.setdefault(conn_id, {})
        state = session_tasks.get(task_id)
        if not state:
            session_tasks[task_id] = {"cancelled": True, "notified": False, "created_at": now}
            return
        state["cancelled"] = True


def _is_task_cancelled(conn_id: str, task_id: str) -> bool:
    with _TASK_LOCK:
        _purge_stale_tasks_locked(time.monotonic())
        state = _TASK_STATE.get(conn_id, {}).get(task_id)
        return bool(state and state.get("cancelled"))


def _mark_task_notified(conn_id: str, task_id: str) -> bool:
    with _TASK_LOCK:
        state = _TASK_STATE.get(conn_id, {}).get(task_id)
        if not state or state.get("notified"):
            return False
        state["notified"] = True
        return True


def _clear_task(conn_id: str, task_id: str) -> None:
    with _TASK_LOCK:
        session_tasks = _TASK_STATE.get(conn_id)
        if not session_tasks:
            return
        session_tasks.pop(task_id, None)
        if not session_tasks:
            _TASK_STATE.pop(conn_id, None)


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
    # Tool start times for duration measurement (keyed by tool name)
    _tool_start_times: dict[str, float] = field(default_factory=dict)

    # --- Helpers ---

    def is_cancelled(self) -> bool:
        return _is_task_cancelled(self.conn_id, self.task_id)

    def _emit(self, event: str, payload: dict) -> None:
        """Emit a JSON message via the registry (sync, from background thread).

        Automatically includes workflow_id so the frontend can route events
        to the correct per-workflow conversation.
        """
        if self.current_workflow_id and "workflow_id" not in payload:
            payload["workflow_id"] = self.current_workflow_id
        self.registry.send_to_sync(self.conn_id, event, payload)

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
        if _mark_task_notified(self.conn_id, self.task_id):
            self._emit("chat_cancelled", {"task_id": self.task_id})

    def stream_chunk(self, chunk: str) -> None:
        """Stream text to frontend character-by-character for typewriter effect."""
        if self.is_cancelled():
            return
        self.did_stream = True
        for char in chunk:
            if self.is_cancelled():
                return
            self._emit("chat_stream", {"chunk": char, "task_id": self.task_id})
            self.registry.sleep_sync(0.005)  # 5ms delay for visible typewriter effect

    def stream_thinking(self, chunk: str) -> None:
        """Stream LLM reasoning/thinking chunks to the frontend."""
        if not chunk or self.is_cancelled():
            return
        self.thinking_chunks.append(chunk)
        self._emit("chat_thinking", {"chunk": chunk, "task_id": self.task_id})

    def heartbeat(self) -> None:
        while not self.done.is_set():
            self.registry.sleep_sync(5)
            if self.done.is_set() or self.is_cancelled():
                break
            self.emit_progress("heartbeat", "Analysing...")

    def flush_tool_summary(self) -> None:
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
                    logger.warning("Failed to log tool call to audit trail", exc_info=True)
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
            if tool in WORKFLOW_EDIT_TOOLS:
                action = result.get("action")
                logger.info(
                    "Emitting workflow_update action=%s tool=%s workflow_id=%s",
                    action, tool, result.get("workflow_id"),
                )
                self._emit("workflow_update", {"action": action, "data": result})

                has_new_vars = isinstance(result.get("new_variables"), list) and result["new_variables"]
                has_removed_vars = isinstance(result.get("removed_variable_ids"), list) and result["removed_variable_ids"]
                if (has_new_vars or has_removed_vars) and self.convo:
                    self._emit("analysis_updated", {
                        "variables": self.convo.orchestrator.workflow_analysis.get("variables", []),
                        "outputs": self.convo.orchestrator.workflow_analysis.get("outputs", []),
                        "task_id": self.task_id,
                    })

            if tool in WORKFLOW_INPUT_TOOLS and self.convo:
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

    def _sync_orchestrator_from_convo(self) -> None:
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
        # Ensure the canvas workflow exists in the database
        if self.current_workflow_id and self.workflow_store:
            existing = self.workflow_store.get_workflow(self.current_workflow_id, self.user_id)
            if not existing:
                try:
                    self.workflow_store.create_workflow(
                        workflow_id=self.current_workflow_id,
                        user_id=self.user_id,
                        name="New Workflow",
                        description="",
                        nodes=[],
                        edges=[],
                        inputs=[],
                        outputs=[],
                        tree={},
                        doubts=[],
                        output_type="string",
                        is_draft=True,
                    )
                    logger.info(
                        "Auto-persisted canvas workflow %s for user %s",
                        self.current_workflow_id, self.user_id,
                    )
                    # Notify the frontend so it can sync its store/URL
                    self._emit("workflow_created", {
                        "workflow_id": self.current_workflow_id,
                        "name": "New Workflow",
                        "is_draft": True,
                    })
                except Exception:
                    logger.exception(
                        "Failed to auto-persist canvas workflow %s",
                        self.current_workflow_id,
                    )
            self.convo.orchestrator.current_workflow_id = self.current_workflow_id
            # Look up workflow name from DB for system prompt display
            if self.workflow_store:
                record = self.workflow_store.get_workflow(self.current_workflow_id, self.user_id)
                if record:
                    self.convo.orchestrator.current_workflow_name = record.name
        self.convo.orchestrator.open_tabs = self.open_tabs or []
        # Inject conversation logger so the orchestrator can log compaction events
        self.convo.orchestrator._conversation_logger = self.conversation_logger
        self.convo.orchestrator._conversation_id = self.convo.id

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

    # --- Main run loop ---

    def run(self) -> None:
        self.emit_progress("start", "Thinking...")
        threading.Thread(target=self.heartbeat, daemon=True).start()

        # Register as active task so resume_task can reconnect after refresh
        task_key = (self.user_id, self.current_workflow_id) if self.current_workflow_id else None
        if task_key:
            with _ACTIVE_TASKS_LOCK:
                _ACTIVE_TASKS[task_key] = self
            # Mark workflow as building so frontend knows a task is in progress
            if self.workflow_store:
                try:
                    self.workflow_store.update_workflow(
                        self.current_workflow_id, self.user_id, building=True,
                    )
                except Exception:
                    logger.debug("Failed to set building=True", exc_info=True)

        try:
            self.convo = self.conversation_store.get_or_create(self.conversation_id)
            if not self._save_uploaded_files():
                return
            self._sync_payload_workflow()
            self._sync_orchestrator_from_convo()

            # Persist conversation_id (and uploaded file metadata) on the workflow
            # so they survive page reloads.
            if self.current_workflow_id and self.workflow_store and self.convo:
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
                    logger.debug("Failed to persist conversation_id/files on workflow", exc_info=True)

            # Ensure the conversation exists in the audit log.
            # Wrapped in try/except so a logging failure never crashes the chat.
            if self.conversation_logger and self.convo:
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
                    logger.warning("Failed to log user message to audit trail", exc_info=True)
            else:
                logger.warning(
                    "Audit log skipped: conversation_logger=%s convo=%s",
                    self.conversation_logger is not None, self.convo is not None,
                )

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

            # Log the assistant response and any accumulated thinking to the audit trail
            if self.conversation_logger and self.convo:
                try:
                    orch = self.convo.orchestrator
                    self.conversation_logger.log_assistant_response(
                        self.convo.id, response_text,
                        input_tokens=orch._last_input_tokens or None,
                        output_tokens=getattr(orch, "_last_output_tokens", None),
                        task_id=self.task_id,
                    )
                    if self.thinking_chunks:
                        self.conversation_logger.log_thinking(
                            self.convo.id, "".join(self.thinking_chunks), task_id=self.task_id,
                        )
                except Exception:
                    logger.warning("Failed to log assistant response to audit trail", exc_info=True)

            # Emit context window usage so the frontend can show an indicator
            orch = self.convo.orchestrator
            self._emit("context_status", {
                "usage_pct": orch.context_usage_pct,
                "input_tokens": orch._last_input_tokens,
                "message_count": len(orch.history),
            })
            if self.is_cancelled():
                self._emit_response(response_text, cancelled=True)
                self.emit_cancelled()
                return
            self._emit_response(response_text)
        except Exception as exc:
            logger.exception("WS chat failed")
            # Log the error to the audit trail
            if self.conversation_logger and self.convo:
                try:
                    self.conversation_logger.log_error(
                        self.convo.id, exc, task_id=self.task_id,
                    )
                except Exception:
                    logger.warning("Failed to log error to audit trail", exc_info=True)
            self.emit_error(str(exc))
        finally:
            self.done.set()
            _clear_task(self.conn_id, self.task_id)
            # Unregister from active tasks and clear building flag
            if task_key:
                with _ACTIVE_TASKS_LOCK:
                    _ACTIVE_TASKS.pop(task_key, None)
                if self.workflow_store:
                    try:
                        self.workflow_store.update_workflow(
                            self.current_workflow_id, self.user_id, building=False,
                        )
                    except Exception:
                        logger.debug("Failed to set building=False", exc_info=True)


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
    _register_task(conn_id, task_id)

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
        current_workflow_id=payload.get("current_workflow_id") or f"wf_{uuid4().hex}",
        open_tabs=payload.get("open_tabs"),
        img_annotations=payload.get("annotations"),
        conversation_logger=conversation_logger,
    )
    threading.Thread(target=task.run, daemon=True, name=f"ws-chat-{task_id}").start()


def handle_cancel_task(
    registry: ConnectionRegistry,
    *,
    conn_id: str,
    payload: Dict[str, Any],
) -> None:
    """Handle cancel_task message."""
    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        return
    _cancel_task(conn_id, task_id)
    if _mark_task_notified(conn_id, task_id):
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

    task_key = (user_id, workflow_id)
    with _ACTIVE_TASKS_LOCK:
        task = _ACTIVE_TASKS.get(task_key)

    if task and not task.done.is_set():
        old_conn_id = task.conn_id
        task.conn_id = conn_id
        logger.info(
            "resume_task: reconnected workflow=%s old_conn=%s new_conn=%s",
            workflow_id, old_conn_id, conn_id,
        )
        # Send an immediate progress event so the frontend knows it's connected
        registry.send_to_sync(conn_id, "chat_progress", {
            "event": "resumed",
            "status": "Processing...",
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
