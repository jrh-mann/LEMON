"""Tests for the Turn state machine.

Validates state transitions, history commit behavior, and audit logging
for all turn outcomes: completed, cancelled, and failed.
"""

from unittest.mock import MagicMock, call

import pytest

from src.backend.agents.turn import Turn, TurnStatus, InvalidTransitionError


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def make_turn(**kwargs):
    """Create a Turn with sensible defaults."""
    defaults = {"user_message": "Add a start node", "conversation_id": "conv_test"}
    defaults.update(kwargs)
    return Turn(**defaults)


class FakeConversationManager:
    """Minimal stand-in for ConversationManager — just needs .history list."""
    def __init__(self):
        self.history = []


# ------------------------------------------------------------------
# State machine tests
# ------------------------------------------------------------------

class TestTurnStateMachine:
    """Verify explicit state transitions and rejection of invalid ones."""

    def test_happy_path_with_tools(self):
        """PENDING → CALLING_LLM → EXECUTING_TOOLS → CALLING_LLM → COMPLETED"""
        turn = make_turn()
        assert turn.status == TurnStatus.PENDING

        turn.start()
        assert turn.status == TurnStatus.CALLING_LLM

        turn.begin_tool_execution()
        assert turn.status == TurnStatus.EXECUTING_TOOLS

        turn.begin_llm_call()
        assert turn.status == TurnStatus.CALLING_LLM

        turn.complete("Done!")
        assert turn.status == TurnStatus.COMPLETED
        assert turn.final_text == "Done!"

    def test_happy_path_no_tools(self):
        """PENDING → CALLING_LLM → COMPLETED (no tool loop)."""
        turn = make_turn()
        turn.start()
        turn.complete("Here's the workflow.")
        assert turn.status == TurnStatus.COMPLETED

    def test_cancel_during_llm(self):
        """PENDING → CALLING_LLM → CANCELLED."""
        turn = make_turn()
        turn.start()
        turn.cancel(["partial ", "text"])
        assert turn.status == TurnStatus.CANCELLED
        assert turn.partial_text == "partial text"

    def test_cancel_during_tools(self):
        """PENDING → CALLING_LLM → EXECUTING_TOOLS → CANCELLED."""
        turn = make_turn()
        turn.start()
        turn.begin_tool_execution()
        turn.cancel(["some ", "output"])
        assert turn.status == TurnStatus.CANCELLED
        assert turn.partial_text == "some output"

    def test_cancel_with_no_chunks(self):
        """Cancel with empty streamed chunks → empty partial_text."""
        turn = make_turn()
        turn.start()
        turn.cancel([])
        assert turn.status == TurnStatus.CANCELLED
        assert turn.partial_text == ""

    def test_cancel_idempotent(self):
        """Calling cancel on already-cancelled turn is a no-op."""
        turn = make_turn()
        turn.start()
        turn.cancel(["first"])
        turn.cancel(["second"])  # Should not change partial_text
        assert turn.partial_text == "first"

    def test_fail_during_llm(self):
        """PENDING → CALLING_LLM → FAILED."""
        turn = make_turn()
        turn.start()
        turn.fail("LLM error: timeout")
        assert turn.status == TurnStatus.FAILED
        assert turn.error == "LLM error: timeout"

    def test_fail_during_tools(self):
        """PENDING → CALLING_LLM → EXECUTING_TOOLS → FAILED."""
        turn = make_turn()
        turn.start()
        turn.begin_tool_execution()
        turn.fail("Tool error (add_node): invalid type")
        assert turn.status == TurnStatus.FAILED

    def test_fail_idempotent(self):
        """Calling fail on already-failed turn is a no-op."""
        turn = make_turn()
        turn.start()
        turn.fail("first error")
        turn.fail("second error")
        assert turn.error == "first error"

    def test_invalid_transition_pending_to_completed(self):
        """Cannot go directly from PENDING to COMPLETED."""
        turn = make_turn()
        with pytest.raises(InvalidTransitionError):
            turn.complete("nope")

    def test_invalid_transition_completed_to_calling(self):
        """Cannot transition out of COMPLETED."""
        turn = make_turn()
        turn.start()
        turn.complete("done")
        with pytest.raises(InvalidTransitionError):
            turn.start()

    def test_invalid_transition_pending_to_executing(self):
        """Cannot go directly from PENDING to EXECUTING_TOOLS."""
        turn = make_turn()
        with pytest.raises(InvalidTransitionError):
            turn.begin_tool_execution()

    def test_invalid_transition_calling_to_begin_llm(self):
        """Cannot go from CALLING_LLM to CALLING_LLM via begin_llm_call."""
        turn = make_turn()
        turn.start()
        with pytest.raises(InvalidTransitionError):
            turn.begin_llm_call()

    def test_multiple_tool_rounds(self):
        """Multiple CALLING_LLM ↔ EXECUTING_TOOLS cycles."""
        turn = make_turn()
        turn.start()
        for _ in range(5):
            turn.begin_tool_execution()
            turn.begin_llm_call()
        turn.complete("After 5 tool rounds.")
        assert turn.status == TurnStatus.COMPLETED


# ------------------------------------------------------------------
# Tool recording tests
# ------------------------------------------------------------------

class TestToolRecording:
    """Verify tool round messages and structured records."""

    def test_add_assistant_tool_use(self):
        """Assistant tool_use message is stored in turn.messages."""
        turn = make_turn()
        msg = {"role": "assistant", "content": "", "tool_calls": [
            {"id": "tc1", "function": {"name": "add_node", "arguments": "{}"}}
        ]}
        turn.add_assistant_tool_use(msg)
        assert len(turn.messages) == 1
        assert turn.messages[0]["role"] == "assistant"

    def test_add_tool_result(self):
        """Tool result is stored in messages + tool_calls."""
        turn = make_turn()
        turn.add_tool_result(
            "tc1", "add_node", {"type": "start"},
            {"success": True, "node_id": "n1"},
            success=True, duration_ms=50,
        )
        assert len(turn.messages) == 1
        assert turn.messages[0]["role"] == "tool"
        assert turn.messages[0]["tool_call_id"] == "tc1"
        assert len(turn.tool_calls) == 1
        assert turn.tool_calls[0] == {
            "tool": "add_node", "arguments": {"type": "start"}, "success": True,
        }

    def test_add_tool_result_with_custom_content(self):
        """Content parameter overrides default JSON serialization."""
        turn = make_turn()
        image_blocks = [{"type": "image", "source": {"type": "base64"}}]
        turn.add_tool_result(
            "tc2", "analyze_image", {}, {"success": True},
            success=True, content=image_blocks,
        )
        assert turn.messages[0]["content"] is image_blocks

    def test_add_skipped_tool(self):
        """Skipped tool adds message + structured record."""
        turn = make_turn()
        turn.add_skipped_tool("tc3", "add_connection", {"from": "n1", "to": "n2"})
        assert len(turn.messages) == 1
        assert turn.messages[0]["role"] == "tool"
        assert len(turn.tool_calls) == 1
        assert turn.tool_calls[0]["success"] is False

    def test_full_tool_round(self):
        """Complete tool round: assistant(tool_use) + tool(result)."""
        turn = make_turn()
        # Assistant requests tool
        turn.add_assistant_tool_use({
            "role": "assistant", "content": "",
            "tool_calls": [{"id": "tc1", "function": {"name": "list_workflows", "arguments": "{}"}}],
        })
        # Tool returns result
        turn.add_tool_result(
            "tc1", "list_workflows", {},
            {"success": True, "count": 3},
            success=True,
        )
        assert len(turn.messages) == 2
        assert [m["role"] for m in turn.messages] == ["assistant", "tool"]


# ------------------------------------------------------------------
# Commit tests — history persistence
# ------------------------------------------------------------------

class TestCommit:
    """Verify Turn.commit() writes correct history entries."""

    def test_commit_completed_no_tools(self):
        """Completed turn without tools: [user, assistant]."""
        turn = make_turn()
        turn.start()
        turn.complete("Here's your workflow.")
        cm = FakeConversationManager()
        turn.commit(cm)
        assert len(cm.history) == 2
        assert cm.history[0] == {"role": "user", "content": "Add a start node"}
        assert cm.history[1] == {"role": "assistant", "content": "Here's your workflow."}

    def test_commit_completed_with_tools(self):
        """Completed turn with tools: [user, asst(tool_use), tool, assistant]."""
        turn = make_turn()
        turn.start()
        turn.begin_tool_execution()
        turn.add_assistant_tool_use({
            "role": "assistant", "content": "",
            "tool_calls": [{"id": "tc1", "function": {"name": "add_node", "arguments": "{}"}}],
        })
        turn.add_tool_result("tc1", "add_node", {}, {"success": True}, success=True)
        turn.begin_llm_call()
        turn.complete("Added the node.")
        cm = FakeConversationManager()
        turn.commit(cm)
        assert len(cm.history) == 4
        roles = [m["role"] for m in cm.history]
        assert roles == ["user", "assistant", "tool", "assistant"]
        assert cm.history[3]["content"] == "Added the node."

    def test_commit_cancelled_with_partial(self):
        """Cancelled turn with partial text: [user, partial, CANCELLED markers]."""
        turn = make_turn()
        turn.start()
        turn.cancel(["I'll create ", "a workflow"])
        cm = FakeConversationManager()
        turn.commit(cm)
        assert len(cm.history) == 4
        assert cm.history[0]["role"] == "user"
        assert cm.history[1] == {"role": "assistant", "content": "I'll create a workflow"}
        assert "[CANCELLED]" in cm.history[2]["content"]
        assert cm.history[3]["content"] == "[CANCELLED]"

    def test_commit_cancelled_no_partial(self):
        """Cancelled turn with no streamed text: [user, CANCELLED markers]."""
        turn = make_turn()
        turn.start()
        turn.cancel([])
        cm = FakeConversationManager()
        turn.commit(cm)
        assert len(cm.history) == 3
        assert cm.history[0]["role"] == "user"
        assert "[CANCELLED]" in cm.history[1]["content"]

    def test_commit_failed_no_tools(self):
        """Failed turn without tools: [user, error]."""
        turn = make_turn()
        turn.start()
        turn.fail("LLM error: rate limit")
        cm = FakeConversationManager()
        turn.commit(cm)
        assert len(cm.history) == 2
        assert cm.history[1]["content"] == "Error: LLM error: rate limit"

    def test_commit_failed_preserves_tools(self):
        """Failed turn with tools: [user, tool_messages..., error]."""
        turn = make_turn()
        turn.start()
        turn.begin_tool_execution()
        turn.add_assistant_tool_use({
            "role": "assistant", "content": "",
            "tool_calls": [{"id": "tc1", "function": {"name": "add_node", "arguments": "{}"}}],
        })
        turn.add_tool_result("tc1", "add_node", {}, {"success": True}, success=True)
        turn.fail("Tool error (modify_node): not found")
        cm = FakeConversationManager()
        turn.commit(cm)
        # Should preserve: user + assistant(tool_use) + tool + error
        assert len(cm.history) == 4
        roles = [m["role"] for m in cm.history]
        assert roles == ["user", "assistant", "tool", "assistant"]
        assert "Error:" in cm.history[3]["content"]

    def test_commit_pending_is_noop(self):
        """Committing a PENDING turn writes nothing."""
        turn = make_turn()
        cm = FakeConversationManager()
        turn.commit(cm)
        assert len(cm.history) == 0

    def test_commit_appends_to_existing_history(self):
        """Commit appends to existing history, doesn't replace it."""
        turn = make_turn()
        turn.start()
        turn.complete("Response.")
        cm = FakeConversationManager()
        cm.history = [
            {"role": "user", "content": "previous"},
            {"role": "assistant", "content": "previous response"},
        ]
        turn.commit(cm)
        assert len(cm.history) == 4
        assert cm.history[0]["content"] == "previous"


# ------------------------------------------------------------------
# Audit logging tests
# ------------------------------------------------------------------

class TestAuditLogging:
    """Verify Turn calls ConversationLogger at the right times."""

    def _make_mock_logger(self):
        return MagicMock()

    def test_start_logs_user_message(self):
        logger = self._make_mock_logger()
        turn = make_turn(conversation_logger=logger, task_id="task_1")
        turn.start()
        logger.log_user_message.assert_called_once_with(
            "conv_test", "Add a start node", files=None, task_id="task_1",
        )

    def test_start_logs_user_message_with_files(self):
        logger = self._make_mock_logger()
        turn = make_turn(conversation_logger=logger)
        files = [{"name": "img.png", "file_type": "image"}]
        turn.start(file_meta=files)
        logger.log_user_message.assert_called_once_with(
            "conv_test", "Add a start node", files=files, task_id=None,
        )

    def test_complete_logs_response(self):
        logger = self._make_mock_logger()
        turn = make_turn(conversation_logger=logger, task_id="task_1")
        turn.start()
        turn.complete("Done!", input_tokens=500, output_tokens=100)
        logger.log_assistant_response.assert_called_once_with(
            "conv_test", "Done!",
            input_tokens=500, output_tokens=100, task_id="task_1",
        )

    def test_add_tool_result_logs_tool_call(self):
        logger = self._make_mock_logger()
        turn = make_turn(conversation_logger=logger, task_id="task_1")
        result = {"success": True, "node_id": "n1"}
        turn.add_tool_result(
            "tc1", "add_node", {"type": "start"}, result,
            success=True, duration_ms=42,
        )
        logger.log_tool_call.assert_called_once_with(
            "conv_test", "add_node", {"type": "start"}, result,
            True, 42, task_id="task_1",
        )

    def test_fail_logs_error(self):
        logger = self._make_mock_logger()
        turn = make_turn(conversation_logger=logger, task_id="task_1")
        turn.start()
        turn.fail("kaboom")
        logger.log_error.assert_called_once_with(
            "conv_test", "kaboom", task_id="task_1",
        )

    def test_no_logger_no_crash(self):
        """All Turn methods work fine without a logger."""
        turn = make_turn(conversation_logger=None)
        turn.start()
        turn.add_tool_result("tc1", "add_node", {}, {}, success=True)
        turn.complete("ok")
        cm = FakeConversationManager()
        turn.commit(cm)
        assert len(cm.history) == 3

    def test_cancel_does_not_log(self):
        """Cancel doesn't call any logger methods (no audit for cancel)."""
        logger = self._make_mock_logger()
        turn = make_turn(conversation_logger=logger)
        turn.start()
        logger.reset_mock()
        turn.cancel(["partial"])
        # Only start() would have logged — after reset, no calls
        assert logger.method_calls == []

    def test_logger_exception_does_not_crash(self):
        """If logger throws, Turn catches and continues."""
        logger = self._make_mock_logger()
        logger.log_user_message.side_effect = RuntimeError("DB locked")
        turn = make_turn(conversation_logger=logger)
        # Should not raise
        turn.start()
        assert turn.status == TurnStatus.CALLING_LLM
