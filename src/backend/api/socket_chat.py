"""Socket chat workflow for the API server."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock
from typing import Any, Dict, Optional
from uuid import uuid4

from flask import request
from flask_socketio import SocketIO

from .common import utc_now
from .conversations import Conversation, ConversationStore
from .response_utils import extract_tool_calls, summarize_response
from .tool_summaries import ToolSummaryTracker
from ..tools.constants import WORKFLOW_EDIT_TOOLS, WORKFLOW_INPUT_TOOLS, WORKFLOW_LIBRARY_TOOLS
from ..utils.uploads import save_uploaded_file, save_annotations
from ..storage.workflows import WorkflowStore

logger = logging.getLogger("backend.api")

_TASK_STATE: Dict[str, Dict[str, Dict[str, Any]]] = {}
_TASK_LOCK = Lock()
_TASK_TTL_SECONDS = 1800.0


def _purge_stale_tasks_locked(now: float) -> None:
    stale_sessions: list[str] = []
    for sid, tasks in _TASK_STATE.items():
        stale_tasks = [
            task_id
            for task_id, state in tasks.items()
            if now - state.get("created_at", now) > _TASK_TTL_SECONDS
        ]
        for task_id in stale_tasks:
            tasks.pop(task_id, None)
        if not tasks:
            stale_sessions.append(sid)
    for sid in stale_sessions:
        _TASK_STATE.pop(sid, None)


def _register_task(sid: str, task_id: str) -> None:
    with _TASK_LOCK:
        now = time.monotonic()
        _purge_stale_tasks_locked(now)
        session_tasks = _TASK_STATE.setdefault(sid, {})
        session_tasks.setdefault(
            task_id,
            {"cancelled": False, "notified": False, "created_at": now},
        )


def _cancel_task(sid: str, task_id: str) -> None:
    with _TASK_LOCK:
        now = time.monotonic()
        _purge_stale_tasks_locked(now)
        session_tasks = _TASK_STATE.setdefault(sid, {})
        state = session_tasks.get(task_id)
        if not state:
            session_tasks[task_id] = {"cancelled": True, "notified": False, "created_at": now}
            return
        state["cancelled"] = True


def _is_task_cancelled(sid: str, task_id: str) -> bool:
    with _TASK_LOCK:
        _purge_stale_tasks_locked(time.monotonic())
        state = _TASK_STATE.get(sid, {}).get(task_id)
        return bool(state and state.get("cancelled"))


def _mark_task_notified(sid: str, task_id: str) -> bool:
    with _TASK_LOCK:
        state = _TASK_STATE.get(sid, {}).get(task_id)
        if not state or state.get("notified"):
            return False
        state["notified"] = True
        return True


def _clear_task(sid: str, task_id: str) -> None:
    with _TASK_LOCK:
        session_tasks = _TASK_STATE.get(sid)
        if not session_tasks:
            return
        session_tasks.pop(task_id, None)
        if not session_tasks:
            _TASK_STATE.pop(sid, None)


@dataclass
class SocketChatTask:
    socketio: SocketIO
    conversation_store: ConversationStore
    repo_root: Path
    workflow_store: WorkflowStore
    user_id: str
    sid: str
    task_id: str
    message: str
    conversation_id: Optional[str]
    files_data: list[dict[str, Any]]  # List of uploaded file dicts from frontend
    workflow: Optional[Dict[str, Any]]
    analysis: Optional[Dict[str, Any]]  # Frontend analysis (variables, outputs, etc)
    current_workflow_id: Optional[str] = None  # ID of current workflow on canvas (None if unsaved)
    open_tabs: Optional[list[Dict[str, Any]]] = None  # All open tabs with unsaved workflows
    done: Event = field(default_factory=Event)
    executed_tools: list[dict[str, Any]] = field(default_factory=list)
    tool_summary: ToolSummaryTracker = field(default_factory=ToolSummaryTracker)
    did_stream: bool = False
    convo: Optional[Conversation] = None
    annotations: Optional[list[dict[str, Any]]] = None
    saved_file_paths: list[dict[str, Any]] = field(default_factory=list)  # Saved file metadata

    def is_cancelled(self) -> bool:
        return _is_task_cancelled(self.sid, self.task_id)

    def emit_progress(self, event: str, status: str, *, tool: Optional[str] = None) -> None:
        payload: Dict[str, Any] = {"event": event, "status": status, "task_id": self.task_id}
        if tool:
            payload["tool"] = tool
        self.socketio.emit("chat_progress", payload, to=self.sid)

    def emit_error(self, error: str) -> None:
        if self.is_cancelled():
            return
        self.socketio.emit("agent_error", {"task_id": self.task_id, "error": error}, to=self.sid)

    def emit_cancelled(self) -> None:
        if _mark_task_notified(self.sid, self.task_id):
            self.socketio.emit("chat_cancelled", {"task_id": self.task_id}, to=self.sid)

    def stream_chunk(self, chunk: str) -> None:
        """Stream text to frontend character-by-character for typewriter effect."""
        if self.is_cancelled():
            return
        self.did_stream = True
        # Emit each character individually for smooth typewriter effect
        # Small delay (5ms) between characters makes the effect visible
        for char in chunk:
            if self.is_cancelled():
                return
            self.socketio.emit("chat_stream", {"chunk": char, "task_id": self.task_id}, to=self.sid)
            self.socketio.sleep(0.005)  # 5ms delay for visible typewriter effect

    def heartbeat(self) -> None:
        while not self.done.is_set():
            self.socketio.sleep(5)
            if self.done.is_set() or self.is_cancelled():
                break
            self.emit_progress("heartbeat", "Analyzing...")

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
        if self.is_cancelled():
            return
        if event == "tool_start":
            self.executed_tools.append({"tool": tool, "arguments": args})
        if tool == "analyze_workflow":
            if event == "tool_progress":
                # Phase-specific progress from the subagent (e.g., "Extracting guidance (1/2)...")
                status = args.get("status", "Analyzing workflow...")
                self.emit_progress(event, status, tool=tool)
            else:
                self.emit_progress(event, "Analyzing workflow...", tool=tool)
        if event == "tool_complete":
            if isinstance(result, dict) and result.get("skipped"):
                return
            success = True
            if isinstance(result, dict) and "success" in result:
                success = bool(result.get("success"))
            self.tool_summary.note(tool, success=success)
            # Store result in executed_tools so it's available in chat response
            # Find the matching tool entry and add the result
            for executed in reversed(self.executed_tools):
                if executed.get("tool") == tool and "result" not in executed:
                    executed["result"] = result
                    executed["success"] = success
                    break
        if event == "tool_batch_complete":
            self.flush_tool_summary()
        # Emit workflow_modified when analysis produces a flowchart — either from
        # publish_latest_analysis or directly from analyze_workflow.
        if tool in ("publish_latest_analysis", "analyze_workflow") and event == "tool_complete" and isinstance(result, dict):
            flowchart = result.get("flowchart") if isinstance(result.get("flowchart"), dict) else None
            if flowchart and flowchart.get("nodes"):
                analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else None
                self.socketio.emit(
                    "workflow_modified",
                    {
                        "action": "create_workflow",
                        "data": {
                            "flowchart": flowchart,
                            "analysis": analysis,
                        },
                    },
                    to=self.sid,
                )

        if tool == "add_image_question" and event == "tool_complete" and isinstance(result, dict) and result.get("success"):
            self.socketio.emit(
                "annotations_update",
                {
                    "annotations": result.get("annotations", [])
                },
                to=self.sid,
            )

        if event == "tool_complete" and isinstance(result, dict) and result.get("success"):
            if tool in WORKFLOW_EDIT_TOOLS:
                self.socketio.emit(
                    "workflow_update",
                    {
                        "action": result.get("action"),
                        "data": result,
                    },
                    to=self.sid,
                )

            if (tool in WORKFLOW_INPUT_TOOLS or tool == "analyze_workflow") and self.convo:
                # Emit variables (unified variable system) - includes inputs, subprocess, calculated
                # Frontend receives under 'variables' key for display in Variables tab
                # Include task_id so frontend can filter out updates for inactive tabs
                self.socketio.emit(
                    "analysis_updated",
                    {
                        "variables": self.convo.orchestrator.workflow_analysis.get("variables", []),
                        "outputs": self.convo.orchestrator.workflow_analysis.get("outputs", []),
                        "task_id": self.task_id,
                    },
                    to=self.sid,
                )

            # Emit workflow_created event when create_workflow succeeds
            # This allows frontend to track the new workflow_id for the current tab
            if tool == "create_workflow":
                self.socketio.emit(
                    "workflow_created",
                    {
                        "workflow_id": result.get("workflow_id"),
                        "name": result.get("name"),
                        "output_type": result.get("output_type"),
                        "is_draft": True,  # Newly created workflows are always drafts
                    },
                    to=self.sid,
                )

            # Emit workflow_saved event when save_workflow_to_library succeeds
            # This allows frontend to update the workflow's draft status
            if tool == "save_workflow_to_library":
                self.socketio.emit(
                    "workflow_saved",
                    {
                        "workflow_id": result.get("workflow_id"),
                        "name": result.get("name"),
                        "is_draft": False,  # Saved workflows are no longer drafts
                        "already_saved": result.get("already_saved", False),
                    },
                    to=self.sid,
                )

    def _save_uploaded_files(self) -> bool:
        """Save all uploaded files to disk and populate self.saved_file_paths."""
        logger.info("_save_uploaded_files: files_data count=%d", len(self.files_data))
        if not self.files_data:
            logger.info("_save_uploaded_files: no files_data, returning early")
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
                self.saved_file_paths.append({
                    "id": file_info.get("id", ""),
                    "name": file_info.get("name", ""),
                    "path": rel_path,
                    "file_type": file_type,
                    "purpose": file_info.get("purpose", "unclassified"),
                })
            except Exception as exc:
                logger.exception("Failed to save uploaded file: %s", file_info.get("name"))
                self.emit_error(f"Invalid file '{file_info.get('name', '?')}': {exc}")
                return False
        # Save annotations alongside the first image if provided
        if self.annotations and isinstance(self.annotations, list) and self.saved_file_paths:
            first_image = next(
                (f for f in self.saved_file_paths if f["file_type"] == "image"), None
            )
            if first_image:
                save_annotations(first_image["path"], self.annotations, repo_root=self.repo_root)
        return True

    def _sync_payload_workflow(self) -> None:
        """Sync workflow and analysis from chat payload to conversation."""
        if not self.convo:
            return
        if isinstance(self.workflow, dict):
            self.convo.update_workflow_state(self.workflow)
        if isinstance(self.analysis, dict):
            # Merge frontend analysis into conversation's workflow_analysis
            # This ensures variables added from frontend UI are available to orchestrator
            self.convo.update_workflow_analysis(self.analysis)

    def _sync_orchestrator_from_convo(self) -> None:
        if not self.convo:
            return
        self.convo.orchestrator.sync_workflow(lambda: self.convo.workflow_state)
        self.convo.orchestrator.sync_workflow_analysis(lambda: self.convo.workflow_analysis)
        # Set workflow_store and user_id for tool access
        self.convo.orchestrator.workflow_store = self.workflow_store
        self.convo.orchestrator.user_id = self.user_id
        # Set current_workflow_id so tools know what's on the canvas
        self.convo.orchestrator.current_workflow_id = self.current_workflow_id
        # Set open_tabs so list_workflows_in_library can show all drafts
        self.convo.orchestrator.open_tabs = self.open_tabs or []

    def _sync_convo_from_orchestrator(self) -> None:
        if not self.convo:
            return
        self.convo.update_workflow_state(self.convo.orchestrator.current_workflow)
        self.convo.update_workflow_analysis(self.convo.orchestrator.workflow_analysis)

    def _emit_response(self, response_text: str) -> None:
        tool_calls = extract_tool_calls(response_text, include_result=False)
        if not tool_calls and self.executed_tools:
            tool_calls = self.executed_tools
        summary = summarize_response(response_text) if tool_calls else ""
        if self.convo:
            self.convo.updated_at = utc_now()
        self.socketio.emit(
            "chat_response",
            {
                "response": summary if tool_calls else ("" if self.did_stream else response_text),
                "conversation_id": self.convo.id if self.convo else "",
                "tool_calls": tool_calls,
                "task_id": self.task_id,
            },
            to=self.sid,
        )

    def run(self) -> None:
        self.emit_progress("start", "Thinking...")
        self.socketio.start_background_task(self.heartbeat)
        try:
            self.convo = self.conversation_store.get_or_create(self.conversation_id)
            if not self._save_uploaded_files():
                return
            self._sync_payload_workflow()
            self._sync_orchestrator_from_convo()
            response_text = self.convo.orchestrator.respond(
                self.message,
                has_files=self.saved_file_paths if self.saved_file_paths else [],
                stream=self.stream_chunk,
                allow_tools=True,
                should_cancel=self.is_cancelled,
                on_tool_event=self.on_tool_event,
            )
            self._sync_convo_from_orchestrator()
            if self.is_cancelled():
                self.emit_cancelled()
                return
            self._emit_response(response_text)
        except Exception as exc:
            logger.exception("Socket chat failed")
            self.emit_error(str(exc))
        finally:
            self.done.set()
            _clear_task(self.sid, self.task_id)

def handle_socket_chat(
    socketio: SocketIO,
    *,
    conversation_store: ConversationStore,
    repo_root: Path,
    workflow_store: Any,
    user_id: str,
    payload: Dict[str, Any],
) -> None:
    message = payload.get("message", "")
    task_id = payload.get("task_id")
    sid = request.sid
    # Debug: log whether files are present in the payload
    raw_files = payload.get("files")
    logger.info(
        "handle_socket_chat: message_len=%d files_present=%s files_count=%d",
        len(message) if isinstance(message, str) else 0,
        raw_files is not None,
        len(raw_files) if isinstance(raw_files, list) else 0,
    )

    if not isinstance(message, str) or not message.strip():
        socketio.emit("agent_error", {"task_id": task_id, "error": "message is required"}, to=sid)
        return

    if not isinstance(task_id, str) or not task_id.strip():
        task_id = uuid4().hex
    _register_task(sid, task_id)
    task = SocketChatTask(
        socketio=socketio,
        conversation_store=conversation_store,
        repo_root=repo_root,
        workflow_store=workflow_store,
        user_id=user_id,
        sid=sid,
        task_id=task_id,
        message=message,
        conversation_id=payload.get("conversation_id"),
        files_data=payload.get("files") or [],
        workflow=payload.get("workflow"),
        analysis=payload.get("analysis"),
        current_workflow_id=payload.get("current_workflow_id"),  # ID of workflow on canvas
        open_tabs=payload.get("open_tabs"),  # All open tabs for list_workflows_in_library
        annotations=payload.get("annotations"),
    )
    socketio.start_background_task(task.run)


def handle_cancel_task(
    socketio: SocketIO,
    *,
    payload: Dict[str, Any],
) -> None:
    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        return
    _cancel_task(request.sid, task_id)
    if _mark_task_notified(request.sid, task_id):
        socketio.emit("chat_cancelled", {"task_id": task_id}, to=request.sid)


def handle_sync_workflow(
    socketio: SocketIO,
    *,
    conversation_store: ConversationStore,
    payload: Dict[str, Any],
) -> None:
    """Handle full workflow sync from frontend.

    Called when:
    - User uploads and analyzes workflow
    - User opens workflow from library
    - User creates new workflow from scratch

    This establishes the backend as source of truth.
    Fire-and-forget - chat messages now carry workflow atomically.
    """
    conversation_id = payload.get("conversation_id")
    workflow = payload.get("workflow")
    source = payload.get("source", "unknown")  # 'upload' | 'library' | 'manual'
    sid = request.sid

    if not conversation_id:
        logger.warning("sync_workflow missing conversation_id")
        return

    if not isinstance(workflow, dict):
        logger.warning("sync_workflow invalid workflow format")
        return

    # Store workflow and analysis in session
    convo = conversation_store.get_or_create(conversation_id)
    convo.update_workflow_state(workflow)

    # Sync analysis (variables, outputs) from frontend to conversation
    analysis = payload.get("analysis")
    if isinstance(analysis, dict):
        convo.update_workflow_analysis(analysis)

    logger.info(
        "Synced workflow conv=%s source=%s nodes=%d edges=%d",
        conversation_id,
        source,
        len(workflow.get("nodes", [])),
        len(workflow.get("edges", []))
    )

    # Acknowledge (for debugging)
    socketio.emit('workflow_synced', {
        'conversation_id': conversation_id,
        'nodes_count': len(workflow.get("nodes", [])),
        'edges_count': len(workflow.get("edges", []))
    }, to=sid)
