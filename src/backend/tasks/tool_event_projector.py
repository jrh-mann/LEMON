"""Tool event projector — translates orchestrator tool lifecycle events
to frontend SSE events.

Extracted from ChatTask. Uses injected callables — no direct reference
to ChatEventChannel, Conversation, or Orchestrator. Testable in isolation.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from .tool_summaries import ToolSummaryTracker
from ..storage.conversation_log import ConversationLogger
from ..tools.constants import WORKFLOW_EDIT_TOOLS, WORKFLOW_INPUT_TOOLS

logger = logging.getLogger("backend.api")


class ToolEventProjector:
    """Projects raw tool lifecycle events into SSE events for the frontend.

    Owns ``executed_tools`` (audit trail) and ``tool_summary`` (batched
    progress descriptions). All external dependencies are injected as
    callables so the projector is decoupled from ChatTask internals.
    """

    def __init__(
        self,
        *,
        task_id: str,
        # --- Emit callables (injected from ChatTask / ChatEventChannel) ---
        publish: Callable[[str, dict], None],
        publish_workflow_state: Callable[[Dict[str, Any]], None],
        emit_progress: Callable[..., None],
        stream_chunk: Callable[[str], None],
        # --- State queries ---
        is_cancelled: Callable[[], bool],
        get_workflow_state_payload: Callable[[], Optional[Dict[str, Any]]],
        get_workflow_analysis: Callable[[], Dict[str, Any]],
        # --- Audit / snapshot callables ---
        conversation_logger: Optional[ConversationLogger] = None,
        get_convo_id: Callable[[], Optional[str]] = lambda: None,
        get_current_workflow: Callable[[], Optional[Dict[str, Any]]] = lambda: None,
    ) -> None:
        self._task_id = task_id
        self._publish = publish
        self._publish_workflow_state = publish_workflow_state
        self._emit_progress = emit_progress
        self._stream_chunk = stream_chunk
        self._is_cancelled = is_cancelled
        self._get_workflow_state_payload = get_workflow_state_payload
        self._get_workflow_analysis = get_workflow_analysis
        self._conversation_logger = conversation_logger
        self._get_convo_id = get_convo_id
        self._get_current_workflow = get_current_workflow

        # Owned state
        self.executed_tools: List[Dict[str, Any]] = []
        self.tool_summary: ToolSummaryTracker = ToolSummaryTracker()

    # --- Public API ---

    def flush_tool_summary(self) -> None:
        """Emit any accumulated tool summary text as a stream chunk."""
        summary = self.tool_summary.flush()
        if summary:
            self._stream_chunk(summary)

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
        cancelled = self._is_cancelled()

        if event == "tool_start":
            entry: Dict[str, Any] = {"tool": tool, "arguments": args}
            if cancelled:
                entry["interrupted"] = True
            self.executed_tools.append(entry)
            # Real-time progress so the user sees which tool is running
            if not cancelled:
                self._emit_progress("tool_start", f"Running {tool}...", tool=tool)

        if event == "tool_complete":
            if isinstance(result, dict) and result.get("skipped"):
                return
            success = True
            if isinstance(result, dict) and "success" in result:
                success = bool(result.get("success"))
            self.tool_summary.note(tool, success=success)
            # Attach result to the matching executed_tools entry
            for executed in reversed(self.executed_tools):
                if executed.get("tool") == tool and "result" not in executed:
                    executed["result"] = result
                    executed["success"] = success
                    if cancelled:
                        executed["interrupted"] = True
                    break
            # Snapshot workflow after successful edit tool calls
            if success and tool in WORKFLOW_EDIT_TOOLS and self._conversation_logger:
                convo_id = self._get_convo_id()
                current_workflow = self._get_current_workflow()
                if convo_id and current_workflow is not None:
                    try:
                        self._conversation_logger.log_workflow_snapshot(
                            convo_id, current_workflow, task_id=self._task_id,
                        )
                    except Exception:
                        logger.error(
                            "Failed to log workflow snapshot: tool=%s conv=%s",
                            tool, convo_id, exc_info=True,
                        )

        if event == "tool_batch_complete":
            self.flush_tool_summary()
            # Update progress so frontend doesn't stay stuck on "Running <tool>..."
            # while the LLM processes tool results (can take 30s+ for images).
            if not cancelled:
                self._emit_progress("thinking", "Thinking...")

        # Skip SSE emissions when cancelled — the task is shutting down
        if cancelled:
            return

        # --- Event-specific SSE projections ---

        if tool == "update_plan" and event == "tool_complete" and isinstance(result, dict):
            self._publish("plan_updated", {"items": result.get("items", [])})

        if tool == "ask_question" and event == "tool_complete" and isinstance(result, dict) and result.get("success"):
            questions = result.get("questions", [])
            for q in questions:
                self._publish("pending_question", {
                    "question": q.get("question", ""),
                    "options": q.get("options", []),
                })

        if event == "tool_complete" and isinstance(result, dict) and result.get("success"):
            payload = self._get_workflow_state_payload()

            if tool in WORKFLOW_EDIT_TOOLS:
                action = result.get("action")
                logger.info(
                    "Emitting workflow_update action=%s tool=%s workflow_id=%s",
                    action, tool, result.get("workflow_id"),
                )
                self._publish("workflow_update", {"action": action, "data": result})
                if payload:
                    self._publish_workflow_state(payload)

                has_new_vars = isinstance(result.get("new_variables"), list) and result["new_variables"]
                has_removed_vars = isinstance(result.get("removed_variable_ids"), list) and result["removed_variable_ids"]
                if has_new_vars or has_removed_vars:
                    analysis = self._get_workflow_analysis()
                    self._publish("analysis_updated", {
                        "variables": analysis.get("variables", []),
                        "outputs": analysis.get("outputs", []),
                        "task_id": self._task_id,
                    })

            if tool in WORKFLOW_INPUT_TOOLS and payload:
                self._publish_workflow_state(payload)
                analysis = self._get_workflow_analysis()
                self._publish("analysis_updated", {
                    "variables": analysis.get("variables", []),
                    "outputs": analysis.get("outputs", []),
                    "task_id": self._task_id,
                })

            if tool == "save_workflow_to_library":
                self._publish("workflow_saved", {
                    "workflow_id": result.get("workflow_id"),
                    "name": result.get("name"),
                    "is_draft": False,
                    "already_saved": result.get("already_saved", False),
                })
