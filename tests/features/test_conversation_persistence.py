"""Tests for conversation history persistence across backend restarts.

Verifies that ConversationStore reloads history from ConversationLogger
when a conversation_id exists in the persistent SQLite log but not in memory.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.backend.api.conversations import ConversationStore
from src.backend.storage.conversation_log import ConversationLogger


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def conversation_logger(tmp_dir):
    return ConversationLogger(tmp_dir / "test_log.sqlite")


@pytest.fixture
def repo_root():
    """Return the actual repo root so build_orchestrator can find tool configs."""
    return Path(__file__).resolve().parent.parent


def _seed_conversation(logger: ConversationLogger, conv_id: str) -> None:
    """Insert a user message and assistant response into the logger."""
    logger.ensure_conversation(conv_id, user_id="u1", workflow_id="wf1", model="test")
    logger.log_user_message(conv_id, "Add a start node to the workflow.")
    logger.log_assistant_response(conv_id, "Done! I added a start node.")


class TestConversationReload:
    def test_reload_history_from_logger(self, repo_root, conversation_logger):
        """get_or_create reloads history when conversation_id exists in logger but not in memory."""
        conv_id = "conv_test_reload"
        _seed_conversation(conversation_logger, conv_id)

        store = ConversationStore(repo_root, conversation_logger=conversation_logger)
        convo = store.get_or_create(conv_id)

        history = convo.orchestrator.conversation.history
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert "start node" in history[0]["content"]
        assert history[1]["role"] == "assistant"
        assert "start node" in history[1]["content"]

    def test_existing_conversation_not_reloaded(self, repo_root, conversation_logger):
        """Second get_or_create returns the in-memory conversation, not a fresh reload."""
        conv_id = "conv_test_existing"
        _seed_conversation(conversation_logger, conv_id)

        store = ConversationStore(repo_root, conversation_logger=conversation_logger)
        convo1 = store.get_or_create(conv_id)
        # Mutate history to prove the second call returns the same object
        convo1.orchestrator.conversation.history.append(
            {"role": "user", "content": "extra message"}
        )
        convo2 = store.get_or_create(conv_id)
        assert convo2 is convo1
        assert len(convo2.orchestrator.conversation.history) == 3  # 2 reloaded + 1 appended

    def test_no_logger_creates_fresh(self, repo_root):
        """ConversationStore without a logger creates conversations with empty history."""
        store = ConversationStore(repo_root)
        convo = store.get_or_create("conv_no_logger")
        assert convo.orchestrator.conversation.history == []

    def test_new_conversation_no_reload(self, repo_root, conversation_logger):
        """Auto-generated conversation_id (no ID provided) doesn't attempt reload."""
        store = ConversationStore(repo_root, conversation_logger=conversation_logger)
        convo = store.get_or_create(None)
        # Should have empty history — no reload attempted for auto-generated IDs
        assert convo.orchestrator.conversation.history == []

    def test_reload_preserves_tool_calls_meta(self, repo_root, conversation_logger):
        """tool_calls_meta is reconstructed from tool_call entries on reload.

        After a backend restart, _reload_history must attach tool call records
        to assistant messages as tool_calls_meta so the frontend can display
        the 'Tools (N)' disclosure.
        """
        conv_id = "conv_test_tool_meta"
        conversation_logger.ensure_conversation(
            conv_id, user_id="u1", workflow_id="wf1", model="test",
        )
        conversation_logger.log_user_message(conv_id, "Add two nodes")
        # Tool calls happen between user message and assistant response
        conversation_logger.log_tool_call(
            conv_id, "add_node", {"label": "Start"}, {"success": True}, True, 50.0,
        )
        conversation_logger.log_tool_call(
            conv_id, "add_node", {"label": "End"}, {"success": True}, True, 40.0,
        )
        conversation_logger.log_assistant_response(conv_id, "Added two nodes.")

        store = ConversationStore(repo_root, conversation_logger=conversation_logger)
        convo = store.get_or_create(conv_id)

        history = convo.orchestrator.conversation.history
        assert len(history) == 2  # user + assistant
        assistant_msg = history[1]
        assert assistant_msg["role"] == "assistant"
        assert "tool_calls_meta" in assistant_msg
        tc = assistant_msg["tool_calls_meta"]
        assert len(tc) == 2
        assert tc[0]["tool"] == "add_node"
        assert tc[0]["arguments"] == {"label": "Start"}
        assert tc[0]["success"] is True
        assert tc[1]["tool"] == "add_node"
        assert tc[1]["arguments"] == {"label": "End"}

    def test_reload_preserves_empty_content_with_tools(self, repo_root, conversation_logger):
        """Assistant messages with empty content but tool calls are preserved.

        The ask_question tool can produce turns where the LLM returns only
        tool calls with no text. These must not be dropped on reload.
        """
        conv_id = "conv_test_empty_content"
        conversation_logger.ensure_conversation(
            conv_id, user_id="u1", workflow_id="wf1", model="test",
        )
        conversation_logger.log_user_message(conv_id, "Tell me about this")
        conversation_logger.log_tool_call(
            conv_id, "ask_question", {"questions": []},
            {"success": True, "action": "question_asked"}, True, 10.0,
        )
        # Empty content — LLM only returned tool calls, no text
        conversation_logger.log_assistant_response(conv_id, "")

        store = ConversationStore(repo_root, conversation_logger=conversation_logger)
        convo = store.get_or_create(conv_id)

        history = convo.orchestrator.conversation.history
        assert len(history) == 2  # user + assistant (not dropped!)
        assistant_msg = history[1]
        assert assistant_msg["role"] == "assistant"
        assert "tool_calls_meta" in assistant_msg
        assert len(assistant_msg["tool_calls_meta"]) == 1
        assert assistant_msg["tool_calls_meta"][0]["tool"] == "ask_question"

    def test_reload_survives_logger_error(self, repo_root, conversation_logger):
        """If the logger throws during reload, the conversation still works (empty history)."""
        store = ConversationStore(repo_root, conversation_logger=conversation_logger)
        with patch.object(
            conversation_logger, "get_conversation_timeline", side_effect=Exception("DB error")
        ):
            convo = store.get_or_create("conv_error")
        # Should gracefully fall back to empty history
        assert convo.orchestrator.conversation.history == []
