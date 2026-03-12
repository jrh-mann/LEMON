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

    def test_reload_survives_logger_error(self, repo_root, conversation_logger):
        """If the logger throws during reload, the conversation still works (empty history)."""
        store = ConversationStore(repo_root, conversation_logger=conversation_logger)
        with patch.object(
            conversation_logger, "get_conversation_timeline", side_effect=Exception("DB error")
        ):
            convo = store.get_or_create("conv_error")
        # Should gracefully fall back to empty history
        assert convo.orchestrator.conversation.history == []
