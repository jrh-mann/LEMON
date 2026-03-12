"""Manages LLM conversation history: storage, compaction, and message building.

Extracted from Orchestrator to separate conversation state management from
workflow state and tool execution. The Orchestrator delegates all history
operations to this class via self.conversation.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional


class ConversationManager:
    """Owns the LLM message history list and all operations on it.

    Responsibilities:
    - Storing the conversation history (self.history)
    - Building the full messages list for LLM calls (system + history + user)
    - Saving completed / cancelled turns to history
    - Compacting history when the context window fills up
    - Tracking context-window token usage estimates
    """

    # Compact when input tokens exceed this % of the context limit.
    _COMPACTION_THRESHOLD_PCT = 70
    # Rough chars-per-token estimate for pre-flight token counting.
    _CHARS_PER_TOKEN = 4

    def __init__(self, context_limit: int = 200_000) -> None:
        self.history: List[Dict[str, Any]] = []
        self._context_limit: int = context_limit
        self._last_input_tokens: int = 0
        self._logger = logging.getLogger(__name__)

        # Optional conversation logger for audit trail (injected by ChatTask)
        self._conversation_logger: Optional[Any] = None
        self._conversation_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Context-window tracking
    # ------------------------------------------------------------------

    @property
    def context_usage_pct(self) -> int:
        """Percentage of context window used by the last LLM call."""
        if not self._last_input_tokens:
            return 0
        return min(100, int(self._last_input_tokens / self._context_limit * 100))

    def update_token_estimate(self, input_tokens: int) -> None:
        """Update the last known input token count from the LLM response."""
        self._last_input_tokens = input_tokens

    # ------------------------------------------------------------------
    # Message building
    # ------------------------------------------------------------------

    def build_messages(
        self, system_prompt: str, user_message: Any
    ) -> List[Dict[str, Any]]:
        """Build the full messages list: system + history + new user message."""
        return [
            {"role": "system", "content": system_prompt},
            *self.history,
            {"role": "user", "content": user_message},
        ]

    # ------------------------------------------------------------------
    # Turn persistence
    # ------------------------------------------------------------------

    def save_turn(
        self, user_message: str, final_text: str,
        tool_messages: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Append a completed turn to history.

        When tool_messages is provided, the full tool-use / tool-result exchange
        is preserved between the user message and final assistant response so the
        LLM has context about executed tools on future turns.
        """
        self.history.append({"role": "user", "content": user_message})
        if tool_messages:
            self.history.extend(tool_messages)
        self.history.append({"role": "assistant", "content": final_text})
        self._logger.debug("History now has %d messages", len(self.history))

    def save_error(self, user_message: str, error_msg: str) -> None:
        """Save an errored turn to history so the LLM has context."""
        self.history.append({"role": "user", "content": user_message})
        self.history.append({"role": "assistant", "content": error_msg})

    def finalize_cancel(
        self,
        user_message: str,
        streamed_chunks: List[str],
    ) -> str:
        """Save a cancelled turn to history, patching dangling tool_use blocks.

        Appends the partial assistant response (if any) plus a system note
        informing the LLM that its previous response was interrupted.

        Returns:
            The partial text streamed before cancellation.
        """
        partial = "".join(streamed_chunks)
        self.history.append({"role": "user", "content": user_message})
        if partial:
            self.history.append({"role": "assistant", "content": partial})
        # Tell the LLM its generation was interrupted. Short markers that
        # the frontend won't render as visible chat bubbles (the old
        # "Understood." text appeared as a duplicate message in the UI).
        self.history.append({
            "role": "user",
            "content": "[CANCELLED] Previous response was interrupted. Resume on next turn.",
        })
        self.history.append({"role": "assistant", "content": "[CANCELLED]"})
        return partial

    # ------------------------------------------------------------------
    # History compaction
    # ------------------------------------------------------------------

    def _estimate_history_tokens(self) -> int:
        """Rough token estimate from history character counts."""
        total_chars = sum(len(str(m.get("content", ""))) for m in self.history)
        return total_chars // self._CHARS_PER_TOKEN

    def _needs_compaction(self) -> bool:
        """Check if history should be compacted before the next LLM call."""
        # Use actual token count from last API call if available
        if self._last_input_tokens > 0:
            return (
                self._last_input_tokens
                > self._context_limit * self._COMPACTION_THRESHOLD_PCT / 100
            )
        # Fallback: estimate from history size (only triggers for very long histories)
        return (
            self._estimate_history_tokens()
            > self._context_limit * self._COMPACTION_THRESHOLD_PCT / 100
        )

    def compact_if_needed(self) -> None:
        """Summarize older history messages if context window is filling up."""
        if not self._needs_compaction():
            return
        if len(self.history) < 6:
            return  # Too few messages to compact

        # Keep the most recent 1/3 of messages (minimum 4)
        keep_count = max(4, len(self.history) // 3)
        old_messages = self.history[:-keep_count]
        recent_messages = self.history[-keep_count:]

        # Log discarded messages to the audit trail before compaction
        if self._conversation_logger and self._conversation_id:
            try:
                self._conversation_logger.log_compaction(
                    self._conversation_id,
                    original_count=len(self.history),
                    summary="[pending]",
                    discarded_messages=old_messages,
                )
            except Exception:
                self._logger.debug(
                    "Failed to log compaction to audit trail", exc_info=True
                )

        # Build a text representation of old messages for the summarizer
        summary_parts = []
        for msg in old_messages:
            role = msg.get("role", "unknown")
            content = str(msg.get("content", ""))
            # Truncate very long individual messages for the summary prompt
            if len(content) > 500:
                content = content[:500] + "..."
            summary_parts.append(f"[{role}]: {content}")
        conversation_text = "\n".join(summary_parts)

        try:
            from ..llm.client import call_llm

            summary = call_llm(
                [
                    {
                        "role": "system",
                        "content": (
                            "Summarize this conversation history concisely. "
                            "Preserve: key decisions made, workflow changes "
                            "(nodes/connections added/modified/deleted), "
                            "errors encountered, current state of the workflow, "
                            "and any pending user requests. "
                            "Be brief but complete — this summary replaces "
                            "the original messages."
                        ),
                    },
                    {"role": "user", "content": conversation_text},
                ],
                caller="conversation_manager",
                request_tag="compaction",
            ).text
            # Replace history with summary + recent messages
            original_len = len(self.history)
            self.history = [
                {
                    "role": "user",
                    "content": (
                        f"[Conversation summary — {len(old_messages)} earlier messages]"
                        f"\n{summary}"
                    ),
                },
                {
                    "role": "assistant",
                    "content": "Understood. I have the context from our earlier conversation.",
                },
                *recent_messages,
            ]
            self._logger.info(
                "Compacted history: %d messages -> summary + %d recent = %d total",
                original_len,
                len(recent_messages),
                len(self.history),
            )
        except Exception as exc:
            # Fallback: hard truncation if compaction LLM call fails
            self._logger.warning(
                "Compaction LLM call failed (%s), falling back to truncation", exc
            )
            self.history = self.history[-50:]
