"""Tests for conversation context."""

import pytest
from datetime import datetime, timezone
from lemon.agent.context import (
    ConversationContext,
    ConversationStore,
    Message,
    MessageRole,
    ToolCall,
    WorkingContext,
    generate_conversation_id,
    generate_message_id,
)


# -----------------------------------------------------------------------------
# Test: ID Generation
# -----------------------------------------------------------------------------

class TestIdGeneration:
    """Tests for ID generation."""

    def test_conversation_id_unique(self):
        """Conversation IDs should be unique."""
        ids = [generate_conversation_id() for _ in range(100)]
        assert len(ids) == len(set(ids))

    def test_conversation_id_format(self):
        """Conversation IDs should be 16 char hex."""
        conv_id = generate_conversation_id()
        assert len(conv_id) == 16
        assert all(c in "0123456789abcdef" for c in conv_id)

    def test_message_id_unique(self):
        """Message IDs should be unique."""
        ids = [generate_message_id() for _ in range(100)]
        assert len(ids) == len(set(ids))

    def test_message_id_format(self):
        """Message IDs should be 12 char hex."""
        msg_id = generate_message_id()
        assert len(msg_id) == 12
        assert all(c in "0123456789abcdef" for c in msg_id)


# -----------------------------------------------------------------------------
# Test: Message
# -----------------------------------------------------------------------------

class TestMessage:
    """Tests for Message dataclass."""

    def test_create_message(self):
        """Should create message with required fields."""
        msg = Message(
            id="test123",
            role=MessageRole.USER,
            content="Hello",
        )
        assert msg.id == "test123"
        assert msg.role == MessageRole.USER
        assert msg.content == "Hello"
        assert isinstance(msg.timestamp, datetime)

    def test_message_with_tool_calls(self):
        """Should include tool calls."""
        tool_call = ToolCall(
            tool_name="search_library",
            arguments={"domain": "nephrology"},
            result={"success": True},
        )
        msg = Message(
            id="test123",
            role=MessageRole.ASSISTANT,
            content="Searching...",
            tool_calls=[tool_call],
        )
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].tool_name == "search_library"

    def test_message_to_dict(self):
        """Should convert to dictionary."""
        msg = Message(
            id="test123",
            role=MessageRole.USER,
            content="Test",
        )
        d = msg.to_dict()

        assert d["id"] == "test123"
        assert d["role"] == "user"
        assert d["content"] == "Test"
        assert "timestamp" in d


# -----------------------------------------------------------------------------
# Test: WorkingContext
# -----------------------------------------------------------------------------

class TestWorkingContext:
    """Tests for WorkingContext."""

    def test_default_context(self):
        """Should have empty defaults."""
        ctx = WorkingContext()
        assert ctx.current_workflow_id is None
        assert ctx.validation_session_id is None
        assert ctx.draft_workflow is None

    def test_to_dict(self):
        """Should convert to dictionary."""
        ctx = WorkingContext(
            current_workflow_id="wf-123",
            current_workflow_name="Test Workflow",
        )
        d = ctx.to_dict()

        assert d["current_workflow_id"] == "wf-123"
        assert d["current_workflow_name"] == "Test Workflow"
        assert d["has_draft"] is False


# -----------------------------------------------------------------------------
# Test: ConversationContext
# -----------------------------------------------------------------------------

class TestConversationContext:
    """Tests for ConversationContext."""

    def test_create_context(self):
        """Should create context with defaults."""
        ctx = ConversationContext()
        assert ctx.id is not None
        assert len(ctx.messages) == 0
        assert ctx.working is not None

    def test_add_user_message(self):
        """Should add user message."""
        ctx = ConversationContext()
        msg = ctx.add_user_message("Hello")

        assert len(ctx.messages) == 1
        assert msg.role == MessageRole.USER
        assert msg.content == "Hello"

    def test_add_assistant_message(self):
        """Should add assistant message with tool calls."""
        ctx = ConversationContext()
        tool_call = ToolCall(
            tool_name="search_library",
            arguments={},
            result=None,
        )
        msg = ctx.add_assistant_message("Found results", tool_calls=[tool_call])

        assert len(ctx.messages) == 1
        assert msg.role == MessageRole.ASSISTANT
        assert len(msg.tool_calls) == 1

    def test_add_system_message(self):
        """Should add system message."""
        ctx = ConversationContext()
        msg = ctx.add_system_message("You are a helpful assistant")

        assert msg.role == MessageRole.SYSTEM

    def test_get_recent_messages(self):
        """Should get recent messages."""
        ctx = ConversationContext()
        for i in range(10):
            ctx.add_user_message(f"Message {i}")

        recent = ctx.get_recent_messages(5)
        assert len(recent) == 5
        assert recent[0].content == "Message 5"
        assert recent[4].content == "Message 9"

    def test_get_messages_for_llm(self):
        """Should format messages for LLM API."""
        ctx = ConversationContext()
        ctx.add_system_message("System prompt")
        ctx.add_user_message("User message")
        ctx.add_assistant_message("Assistant response")

        messages = ctx.get_messages_for_llm()

        assert len(messages) == 3
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[2]["role"] == "assistant"

    def test_clear_history(self):
        """Should clear history keeping system messages."""
        ctx = ConversationContext()
        ctx.add_system_message("System")
        ctx.add_user_message("User 1")
        ctx.add_assistant_message("Assistant 1")

        ctx.clear_history(keep_system=True)

        assert len(ctx.messages) == 1
        assert ctx.messages[0].role == MessageRole.SYSTEM

    def test_clear_history_all(self):
        """Should clear all history."""
        ctx = ConversationContext()
        ctx.add_system_message("System")
        ctx.add_user_message("User")

        ctx.clear_history(keep_system=False)

        assert len(ctx.messages) == 0

    def test_set_current_workflow(self):
        """Should set current workflow."""
        ctx = ConversationContext()
        ctx.set_current_workflow("wf-123", "Test Workflow")

        assert ctx.working.current_workflow_id == "wf-123"
        assert ctx.working.current_workflow_name == "Test Workflow"

    def test_set_validation_session(self):
        """Should set validation session."""
        ctx = ConversationContext()
        ctx.set_validation_session("session-456")

        assert ctx.working.validation_session_id == "session-456"

    def test_clear_validation_session(self):
        """Should clear validation session."""
        ctx = ConversationContext()
        ctx.set_validation_session("session-456")
        ctx.clear_validation_session()

        assert ctx.working.validation_session_id is None

    def test_history_trimming(self):
        """Should trim history when exceeding max length."""
        ctx = ConversationContext(max_history_length=10)
        ctx.add_system_message("System")

        for i in range(15):
            ctx.add_user_message(f"Message {i}")

        # Should keep system message + last 9 messages
        assert len(ctx.messages) == 10
        assert ctx.messages[0].role == MessageRole.SYSTEM

    def test_to_dict(self):
        """Should convert to dictionary."""
        ctx = ConversationContext(user_id="user-123")
        ctx.add_user_message("Hello")

        d = ctx.to_dict()

        assert d["id"] == ctx.id
        assert d["user_id"] == "user-123"
        assert d["message_count"] == 1
        assert "working" in d


# -----------------------------------------------------------------------------
# Test: ConversationStore
# -----------------------------------------------------------------------------

class TestConversationStore:
    """Tests for ConversationStore."""

    def test_create_conversation(self):
        """Should create new conversation."""
        store = ConversationStore()
        ctx = store.create()

        assert ctx.id is not None
        assert store.get(ctx.id) is ctx

    def test_create_with_user_id(self):
        """Should create conversation with user ID."""
        store = ConversationStore()
        ctx = store.create(user_id="user-123")

        assert ctx.user_id == "user-123"

    def test_get_nonexistent(self):
        """Should return None for non-existent conversation."""
        store = ConversationStore()
        result = store.get("nonexistent")

        assert result is None

    def test_delete_conversation(self):
        """Should delete conversation."""
        store = ConversationStore()
        ctx = store.create()

        result = store.delete(ctx.id)

        assert result is True
        assert store.get(ctx.id) is None

    def test_delete_nonexistent(self):
        """Should return False for non-existent."""
        store = ConversationStore()
        result = store.delete("nonexistent")

        assert result is False

    def test_list_for_user(self):
        """Should list conversations for a user."""
        store = ConversationStore()
        store.create(user_id="user-1")
        store.create(user_id="user-1")
        store.create(user_id="user-2")

        user1_convs = store.list_for_user("user-1")
        user2_convs = store.list_for_user("user-2")

        assert len(user1_convs) == 2
        assert len(user2_convs) == 1
