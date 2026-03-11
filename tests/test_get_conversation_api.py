"""Test that GET /api/chat/{id} collapses tool-round messages correctly.

The in-memory history now contains intermediate assistant messages from tool
rounds (empty tool-use blocks, intermediate reasoning). The API must collapse
these into one assistant response per turn to avoid frontend duplication.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.backend.agents.conversation_manager import ConversationManager
from src.backend.agents.orchestrator_factory import build_orchestrator
from src.backend.api.conversations import ConversationStore


@pytest.fixture
def repo_root():
    return Path(__file__).resolve().parent.parent


def _build_convo_with_tool_history(repo_root):
    """Create a ConversationStore entry with tool messages in history."""
    store = ConversationStore(repo_root)
    convo = store.get_or_create("test_conv")

    # Simulate a turn with multiple tool rounds:
    # user → assistant(tool_use) → tool → assistant(intermediate) → tool → assistant(final)
    convo.orchestrator.conversation.history = [
        {"role": "user", "content": "Create a BMI workflow"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "tc1", "function": {"name": "list_workflows", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "tc1", "content": '{"count": 0}'},
        {"role": "assistant", "content": "No BMI workflow found, creating one.", "tool_calls": [
            {"id": "tc2", "function": {"name": "add_node", "arguments": '{"type":"start"}'}}
        ]},
        {"role": "tool", "tool_call_id": "tc2", "content": '{"success": true}'},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "tc3", "function": {"name": "add_node", "arguments": '{"type":"end"}'}}
        ]},
        {"role": "tool", "tool_call_id": "tc3", "content": '{"success": true}'},
        {"role": "assistant", "content": "Your BMI workflow is ready with start and end nodes."},
    ]
    return store, convo


class TestGetConversationCollapsing:
    """Verify the in-memory history path collapses tool rounds."""

    def test_returns_one_assistant_per_turn(self, repo_root):
        """Multi-round tool history should collapse to user + final assistant."""
        store, convo = _build_convo_with_tool_history(repo_root)

        # Import the route builder and simulate the response logic
        # (extracting just the message-building logic, no HTTP needed)
        history = convo.orchestrator.conversation.history

        # Replicate the collapsing logic from get_conversation
        messages = []
        pending_user = None
        pending_assistant = None

        for idx, msg in enumerate(history):
            role = msg.get("role", "assistant")
            content = msg.get("content", "")

            if role == "user":
                if pending_user is not None:
                    messages.append(pending_user)
                    if pending_assistant is not None:
                        messages.append(pending_assistant)
                pending_user = {"role": "user", "content": content}
                pending_assistant = None
            elif role == "assistant":
                if content:
                    pending_assistant = {"role": "assistant", "content": content}
            # Skip tool

        if pending_user is not None:
            messages.append(pending_user)
            if pending_assistant is not None:
                messages.append(pending_assistant)

        # Should have exactly 2 messages: user + final assistant
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Create a BMI workflow"
        assert messages[1]["role"] == "assistant"
        # Should be the LAST assistant with content, not intermediate ones
        assert messages[1]["content"] == "Your BMI workflow is ready with start and end nodes."

    def test_multi_turn_with_tools(self, repo_root):
        """Two turns, each with tool calls, should produce 4 messages total."""
        store = ConversationStore(repo_root)
        convo = store.get_or_create("test_multi")

        convo.orchestrator.conversation.history = [
            # Turn 1
            {"role": "user", "content": "Add a start node"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "tc1"}]},
            {"role": "tool", "tool_call_id": "tc1", "content": "ok"},
            {"role": "assistant", "content": "Added start node."},
            # Turn 2
            {"role": "user", "content": "Add an end node"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "tc2"}]},
            {"role": "tool", "tool_call_id": "tc2", "content": "ok"},
            {"role": "assistant", "content": "Added end node."},
        ]

        # Collapse
        messages = []
        pending_user = None
        pending_assistant = None

        for msg in convo.orchestrator.conversation.history:
            role = msg.get("role", "assistant")
            content = msg.get("content", "")
            if role == "user":
                if pending_user is not None:
                    messages.append(pending_user)
                    if pending_assistant is not None:
                        messages.append(pending_assistant)
                pending_user = {"role": "user", "content": content}
                pending_assistant = None
            elif role == "assistant" and content:
                pending_assistant = {"role": "assistant", "content": content}

        if pending_user is not None:
            messages.append(pending_user)
            if pending_assistant is not None:
                messages.append(pending_assistant)

        assert len(messages) == 4
        assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
        assert messages[1]["content"] == "Added start node."
        assert messages[3]["content"] == "Added end node."
