"""Turn state machine — wraps a single user→assistant exchange.

A Turn tracks the full lifecycle of one conversation turn, including any
tool loops. It centralizes:
  - State transitions (PENDING → CALLING_LLM ↔ EXECUTING_TOOLS → terminal)
  - Tool round message tracking (for LLM context and history persistence)
  - Audit logging (ConversationLogger writes)
  - History persistence (commit to ConversationManager)

This replaces the scattered save_turn/finalize_cancel/save_error calls that
were spread across orchestrator.py, ws_chat.py, and conversation_manager.py.
"""

from __future__ import annotations

import json
import logging
import time
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TurnStatus(Enum):
    """Explicit states for a conversation turn."""
    PENDING = "pending"              # Created, not yet started
    CALLING_LLM = "calling_llm"     # Waiting for LLM response
    EXECUTING_TOOLS = "executing_tools"  # Running tool batch
    COMPLETED = "completed"          # Turn finished successfully
    CANCELLED = "cancelled"          # User cancelled mid-turn
    FAILED = "failed"                # Turn hit an error


# Valid state transitions — maps current status → set of allowed next statuses
_VALID_TRANSITIONS: Dict[TurnStatus, set] = {
    TurnStatus.PENDING: {TurnStatus.CALLING_LLM},
    TurnStatus.CALLING_LLM: {
        TurnStatus.EXECUTING_TOOLS,  # LLM returned tool_calls
        TurnStatus.COMPLETED,        # LLM returned text only
        TurnStatus.CANCELLED,        # User cancelled during LLM call
        TurnStatus.FAILED,           # LLM call failed
    },
    TurnStatus.EXECUTING_TOOLS: {
        TurnStatus.CALLING_LLM,      # Tools done, calling LLM again
        TurnStatus.COMPLETED,        # ask_question tool → done
        TurnStatus.CANCELLED,        # User cancelled during tool execution
        TurnStatus.FAILED,           # Tool threw exception
    },
    # Terminal states — no transitions out
    TurnStatus.COMPLETED: set(),
    TurnStatus.CANCELLED: set(),
    TurnStatus.FAILED: set(),
}


class Turn:
    """Wraps a single user→assistant exchange including tool loops.

    Created by the caller (WsChatTask/REST handler), passed into
    orchestrator.respond(). The caller handles commit() after respond returns.
    """

    def __init__(
        self,
        user_message: str,
        conversation_id: str,
        *,
        conversation_logger: Optional[Any] = None,
        task_id: Optional[str] = None,
    ) -> None:
        self.status = TurnStatus.PENDING
        self.user_message = user_message
        self.conversation_id = conversation_id
        self._logger = conversation_logger
        self._task_id = task_id

        # Tool round messages: assistant(tool_use) + tool(result) pairs.
        # Used for LLM context in subsequent tool rounds AND persisted to history.
        self.messages: List[Dict[str, Any]] = []

        # Structured tool call records for frontend display badges
        self.tool_calls: List[Dict[str, Any]] = []

        # Final state
        self.final_text: Optional[str] = None
        self.partial_text: str = ""
        self.error: Optional[str] = None

        # Token usage from LLM calls
        self.input_tokens: int = 0
        self.output_tokens: int = 0

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def _transition(self, new_status: TurnStatus) -> None:
        """Validate and perform a state transition."""
        allowed = _VALID_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition from {self.status.value} to {new_status.value}"
            )
        self.status = new_status

    def start(self, *, file_meta: Optional[List[Dict[str, Any]]] = None) -> None:
        """PENDING → CALLING_LLM. Logs user message to audit trail."""
        self._transition(TurnStatus.CALLING_LLM)
        if self._logger:
            try:
                self._logger.log_user_message(
                    self.conversation_id, self.user_message,
                    files=file_meta, task_id=self._task_id,
                )
            except Exception:
                logger.error(
                    "Turn: failed to log user message conv=%s",
                    self.conversation_id, exc_info=True,
                )

    def begin_tool_execution(self) -> None:
        """CALLING_LLM|EXECUTING_TOOLS → EXECUTING_TOOLS."""
        self._transition(TurnStatus.EXECUTING_TOOLS)

    def begin_llm_call(self) -> None:
        """EXECUTING_TOOLS → CALLING_LLM (for next tool round)."""
        self._transition(TurnStatus.CALLING_LLM)

    def complete(
        self,
        final_text: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> None:
        """Mark turn as completed. Logs assistant response to audit trail."""
        self._transition(TurnStatus.COMPLETED)
        self.final_text = final_text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        if self._logger:
            try:
                self._logger.log_assistant_response(
                    self.conversation_id, final_text,
                    input_tokens=input_tokens or None,
                    output_tokens=output_tokens or None,
                    task_id=self._task_id,
                )
            except Exception:
                logger.error(
                    "Turn: failed to log assistant response conv=%s",
                    self.conversation_id, exc_info=True,
                )

    def cancel(self, streamed_chunks: List[str]) -> None:
        """Mark turn as cancelled. Can be called from any active state."""
        # Allow cancel from any non-terminal state
        if self.status in (TurnStatus.COMPLETED, TurnStatus.CANCELLED, TurnStatus.FAILED):
            return  # Already terminal, ignore
        self.status = TurnStatus.CANCELLED
        self.partial_text = "".join(streamed_chunks)

    def fail(self, error: str) -> None:
        """Mark turn as failed. Logs error to audit trail."""
        # Allow fail from any non-terminal state
        if self.status in (TurnStatus.COMPLETED, TurnStatus.CANCELLED, TurnStatus.FAILED):
            return  # Already terminal, ignore
        self.status = TurnStatus.FAILED
        self.error = error
        if self._logger:
            try:
                self._logger.log_error(
                    self.conversation_id, error, task_id=self._task_id,
                )
            except Exception:
                logger.error(
                    "Turn: failed to log error conv=%s",
                    self.conversation_id, exc_info=True,
                )

    # ------------------------------------------------------------------
    # Tool round recording
    # ------------------------------------------------------------------

    def add_assistant_tool_use(self, msg: Dict[str, Any]) -> None:
        """Record an assistant message containing tool_calls for LLM context."""
        self.messages.append(msg)

    def add_tool_result(
        self,
        tool_call_id: str,
        name: str,
        args: Dict[str, Any],
        result: Any,
        *,
        success: bool,
        duration_ms: float = 0,
        content: Any = None,
    ) -> None:
        """Record a completed tool result.

        Appends the tool message to self.messages (for LLM context + history),
        appends a structured record to self.tool_calls (for frontend display),
        and logs to the audit trail.
        """
        # Build tool result message for LLM context
        if content is not None:
            # Caller provided pre-built content (e.g. image blocks)
            msg_content = content
        elif isinstance(result, dict):
            msg_content = json.dumps(result)
        else:
            msg_content = str(result)

        # Native Anthropic format: tool results are user messages with
        # tool_result content blocks
        self.messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_call_id,
                "content": msg_content,
            }],
        })

        # Structured record for frontend
        self.tool_calls.append({
            "tool": name,
            "arguments": args,
            "success": success,
        })

        # Audit log
        if self._logger:
            try:
                self._logger.log_tool_call(
                    self.conversation_id, name, args, result, success,
                    duration_ms, task_id=self._task_id,
                )
            except Exception:
                logger.error(
                    "Turn: failed to log tool call %s conv=%s",
                    name, self.conversation_id, exc_info=True,
                )

    def add_skipped_tool(
        self,
        tool_call_id: str,
        name: str,
        args: Dict[str, Any],
    ) -> None:
        """Record a skipped tool (previous tool in batch failed)."""
        skip_data = {
            "success": False, "skipped": True,
            "error": f"Skipped {name} — previous tool failed.",
        }
        self.messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_call_id,
                "content": json.dumps(skip_data),
            }],
        })
        self.tool_calls.append({
            "tool": name,
            "arguments": args,
            "success": False,
        })

    # ------------------------------------------------------------------
    # Persistence — single write point for conversation history
    # ------------------------------------------------------------------

    def commit(self, conversation_manager: Any) -> None:
        """Write this turn's messages to ConversationManager.history.

        This is the SINGLE POINT where conversation history is mutated.
        Replaces save_turn(), finalize_cancel(), and save_error().
        """
        if self.status == TurnStatus.COMPLETED:
            conversation_manager.history.append(
                {"role": "user", "content": self.user_message}
            )
            if self.messages:
                conversation_manager.history.extend(self.messages)
            # Embed structured tool_calls on the final assistant message so
            # get_conversation can read them directly instead of reconstructing
            # from ConversationLogger with fragile index-based matching.
            final_msg: Dict[str, Any] = {
                "role": "assistant", "content": self.final_text,
            }
            if self.tool_calls:
                final_msg["tool_calls_meta"] = list(self.tool_calls)
            conversation_manager.history.append(final_msg)

        elif self.status == TurnStatus.CANCELLED:
            conversation_manager.history.append(
                {"role": "user", "content": self.user_message}
            )
            if self.partial_text:
                conversation_manager.history.append(
                    {"role": "assistant", "content": self.partial_text}
                )
            # Tell the LLM its generation was interrupted
            conversation_manager.history.append({
                "role": "user",
                "content": "[CANCELLED] Previous response was interrupted. Resume on next turn.",
            })
            conversation_manager.history.append(
                {"role": "assistant", "content": "[CANCELLED]"}
            )

        elif self.status == TurnStatus.FAILED:
            conversation_manager.history.append(
                {"role": "user", "content": self.user_message}
            )
            # Preserve tool context so LLM knows what ran before the failure
            if self.messages:
                conversation_manager.history.extend(self.messages)
            conversation_manager.history.append(
                {"role": "assistant", "content": f"Error: {self.error}"}
            )

        elif self.status == TurnStatus.PENDING:
            # Turn was never started — nothing to commit
            return

        else:
            logger.warning(
                "Turn.commit() called with unexpected status %s", self.status.value
            )
            return

        logger.debug(
            "Turn committed: status=%s conv=%s history_len=%d",
            self.status.value, self.conversation_id,
            len(conversation_manager.history),
        )


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    pass
