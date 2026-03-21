"""Tests for chat_turn_runner.run_turn — orchestrator turn lifecycle.

Covers:
1. Happy path: Turn created, respond() called, result is COMPLETED
2. CancellationError: Turn cancelled, result reflects partial text
3. Generic exception: Turn failed, result carries the error
4. Audit DB ensure_conversation called when logger present
5. File metadata passed to turn.start()
6. Ports wired correctly to orchestrator.respond() kwargs
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

from src.backend.tasks.chat_turn_runner import ChatRuntimePorts, TurnResult, run_turn
from src.backend.agents.turn import TurnStatus
from src.backend.utils.cancellation import CancellationError


def _make_ports(**overrides) -> ChatRuntimePorts:
    defaults = dict(
        stream_chunk=MagicMock(),
        stream_thinking=MagicMock(),
        on_tool_event=MagicMock(),
        is_cancelled=MagicMock(return_value=False),
        get_stream_buffer=MagicMock(return_value=""),
        conversation_logger=MagicMock(),
    )
    defaults.update(overrides)
    return ChatRuntimePorts(**defaults)


def _make_convo(*, respond_return="Hello!"):
    """Build a minimal Conversation-like object with mock orchestrator."""
    orch = MagicMock()
    orch.respond.return_value = respond_return
    orch.conversation._last_input_tokens = 100
    orch.conversation.context_usage_pct = 0.25
    orch.conversation.history = [1, 2, 3]
    # getattr fallback for _last_output_tokens
    orch._last_output_tokens = 50

    convo = MagicMock()
    convo.id = "conv-test"
    convo.orchestrator = orch
    return convo


# ── Happy path ───────────────────────────────────────────

class TestHappyPath:
    @patch("src.backend.tasks.chat_turn_runner.Turn")
    def test_returns_completed_result(self, MockTurn):
        mock_turn = MockTurn.return_value
        mock_turn.status = TurnStatus.CALLING_LLM

        convo = _make_convo(respond_return="LLM says hi")
        ports = _make_ports()

        result = run_turn(
            convo=convo, message="hello", task_id="t1",
            user_id="u1", workflow_id="wf-1",
            saved_file_paths=[], ports=ports,
        )

        assert result.status == TurnStatus.COMPLETED
        assert result.response_text == "LLM says hi"
        assert result.cancelled is False
        assert result.error is None
        assert result.input_tokens == 100
        assert result.output_tokens == 50

    @patch("src.backend.tasks.chat_turn_runner.Turn")
    def test_calls_respond_with_correct_kwargs(self, MockTurn):
        convo = _make_convo()
        ports = _make_ports()

        run_turn(
            convo=convo, message="build something", task_id="t1",
            user_id="u1", workflow_id="wf-1",
            saved_file_paths=[{"name": "img.png", "file_type": "image"}],
            ports=ports,
        )

        convo.orchestrator.respond.assert_called_once()
        kwargs = convo.orchestrator.respond.call_args
        assert kwargs.args[0] == "build something"
        assert kwargs.kwargs["stream"] == ports.stream_chunk
        assert kwargs.kwargs["on_thinking"] == ports.stream_thinking
        assert kwargs.kwargs["on_tool_event"] == ports.on_tool_event
        assert kwargs.kwargs["should_cancel"] == ports.is_cancelled
        assert kwargs.kwargs["thinking"] is True
        assert kwargs.kwargs["allow_tools"] is True

    @patch("src.backend.tasks.chat_turn_runner.Turn")
    def test_turn_complete_and_commit_called(self, MockTurn):
        mock_turn = MockTurn.return_value
        mock_turn.status = TurnStatus.CALLING_LLM

        convo = _make_convo(respond_return="done")
        ports = _make_ports()

        run_turn(
            convo=convo, message="go", task_id="t1",
            user_id="u1", workflow_id=None,
            saved_file_paths=[], ports=ports,
        )

        mock_turn.complete.assert_called_once()
        mock_turn.commit.assert_called_once_with(convo.orchestrator.conversation)


# ── Cancellation ─────────────────────────────────────────

class TestCancellation:
    @patch("src.backend.tasks.chat_turn_runner.Turn")
    def test_returns_cancelled_result(self, MockTurn):
        mock_turn = MockTurn.return_value
        mock_turn.status = TurnStatus.CALLING_LLM
        mock_turn.partial_text = "partial..."

        convo = _make_convo()
        convo.orchestrator.respond.side_effect = CancellationError("cancelled")
        ports = _make_ports(get_stream_buffer=MagicMock(return_value="streamed so far"))

        result = run_turn(
            convo=convo, message="hello", task_id="t1",
            user_id="u1", workflow_id="wf-1",
            saved_file_paths=[], ports=ports,
        )

        assert result.status == TurnStatus.CANCELLED
        assert result.cancelled is True
        mock_turn.cancel.assert_called_once_with(["streamed so far"])
        mock_turn.commit.assert_called_once()

    @patch("src.backend.tasks.chat_turn_runner.Turn")
    def test_skips_cancel_if_already_terminal(self, MockTurn):
        mock_turn = MockTurn.return_value
        mock_turn.status = TurnStatus.COMPLETED
        mock_turn.partial_text = ""

        convo = _make_convo()
        convo.orchestrator.respond.side_effect = CancellationError("cancelled")
        ports = _make_ports()

        result = run_turn(
            convo=convo, message="hello", task_id="t1",
            user_id="u1", workflow_id="wf-1",
            saved_file_paths=[], ports=ports,
        )

        assert result.cancelled is True
        mock_turn.cancel.assert_not_called()


# ── Generic failure ──────────────────────────────────────

class TestFailure:
    @patch("src.backend.tasks.chat_turn_runner.Turn")
    def test_returns_failed_result(self, MockTurn):
        mock_turn = MockTurn.return_value
        mock_turn.status = TurnStatus.CALLING_LLM

        convo = _make_convo()
        convo.orchestrator.respond.side_effect = RuntimeError("boom")
        ports = _make_ports()

        result = run_turn(
            convo=convo, message="hello", task_id="t1",
            user_id="u1", workflow_id="wf-1",
            saved_file_paths=[], ports=ports,
        )

        assert result.status == TurnStatus.FAILED
        assert isinstance(result.error, RuntimeError)
        assert str(result.error) == "boom"
        mock_turn.fail.assert_called_once_with("boom")
        mock_turn.commit.assert_called_once()


# ── Audit logging ────────────────────────────────────────

class TestAuditLogging:
    @patch("src.backend.tasks.chat_turn_runner.Turn")
    def test_ensures_conversation_in_audit_db(self, MockTurn):
        convo = _make_convo()
        ports = _make_ports()

        run_turn(
            convo=convo, message="hello", task_id="t1",
            user_id="u1", workflow_id="wf-1",
            saved_file_paths=[], ports=ports,
        )

        ports.conversation_logger.ensure_conversation.assert_called_once_with(
            "conv-test", user_id="u1", workflow_id="wf-1", model="claude-sonnet-4-6",
        )

    @patch("src.backend.tasks.chat_turn_runner.Turn")
    def test_passes_file_meta_to_turn_start(self, MockTurn):
        mock_turn = MockTurn.return_value
        mock_turn.status = TurnStatus.CALLING_LLM
        convo = _make_convo()
        ports = _make_ports()

        files = [{"name": "img.png", "file_type": "image", "path": "/tmp/img.png"}]
        run_turn(
            convo=convo, message="hello", task_id="t1",
            user_id="u1", workflow_id="wf-1",
            saved_file_paths=files, ports=ports,
        )

        mock_turn.start.assert_called_once_with(
            file_meta=[{"name": "img.png", "file_type": "image"}],
        )

    @patch("src.backend.tasks.chat_turn_runner.Turn")
    def test_no_file_meta_when_no_files(self, MockTurn):
        mock_turn = MockTurn.return_value
        mock_turn.status = TurnStatus.CALLING_LLM
        convo = _make_convo()
        ports = _make_ports()

        run_turn(
            convo=convo, message="hello", task_id="t1",
            user_id="u1", workflow_id="wf-1",
            saved_file_paths=[], ports=ports,
        )

        mock_turn.start.assert_called_once_with(file_meta=None)
