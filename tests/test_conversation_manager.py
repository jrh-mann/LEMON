"""Tests for ConversationManager tool message persistence.

Verifies that tool-use and tool-result messages are preserved in history
between turns, so the LLM has context about previously executed tools.
"""

from src.backend.agents.conversation_manager import ConversationManager


class TestToolMessagePersistence:
    def test_save_turn_without_tools(self):
        """Basic save_turn without tool messages works as before."""
        cm = ConversationManager()
        cm.save_turn("hello", "hi there")
        assert len(cm.history) == 2
        assert cm.history[0] == {"role": "user", "content": "hello"}
        assert cm.history[1] == {"role": "assistant", "content": "hi there"}

    def test_save_turn_with_tool_messages(self):
        """Tool messages are preserved between user and final assistant response."""
        cm = ConversationManager()
        tool_msgs = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "tc_1", "function": {"name": "list_workflows", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc_1", "content": '{"workflows": [], "count": 0}'},
        ]
        cm.save_turn("find workflows", "No workflows found.", tool_messages=tool_msgs)

        assert len(cm.history) == 4
        assert cm.history[0]["role"] == "user"
        assert cm.history[1]["role"] == "assistant"
        assert "tool_calls" in cm.history[1]
        assert cm.history[2]["role"] == "tool"
        assert cm.history[3] == {"role": "assistant", "content": "No workflows found."}

    def test_tool_messages_appear_in_build_messages(self):
        """build_messages includes tool messages from previous turns."""
        cm = ConversationManager()
        tool_msgs = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "tc_1", "function": {"name": "add_node", "arguments": '{"type": "start"}'}}
            ]},
            {"role": "tool", "tool_call_id": "tc_1", "content": '{"success": true}'},
        ]
        cm.save_turn("add a start node", "Added a start node.", tool_messages=tool_msgs)

        messages = cm.build_messages("system prompt", "what did you add?")
        # Expected: [system, user, assistant(tool_use), tool_result, assistant(final), user(new)]
        assert len(messages) == 6
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "add a start node"
        assert messages[2]["role"] == "assistant"
        assert "tool_calls" in messages[2]
        assert messages[3]["role"] == "tool"
        assert messages[4]["role"] == "assistant"
        assert messages[4]["content"] == "Added a start node."
        assert messages[5]["role"] == "user"
        assert messages[5]["content"] == "what did you add?"

    def test_multiple_tool_rounds_preserved(self):
        """Multiple rounds of tool calls within a turn are all preserved."""
        cm = ConversationManager()
        tool_msgs = [
            # Round 1: check library
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "tc_1", "function": {"name": "list_workflows", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc_1", "content": '{"count": 0}'},
            # Round 2: create subworkflow
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "tc_2", "function": {"name": "create_subworkflow", "arguments": '{"name": "BMI"}'}}
            ]},
            {"role": "tool", "tool_call_id": "tc_2", "content": '{"success": true}'},
        ]
        cm.save_turn("create BMI subworkflow", "Created BMI subworkflow.", tool_messages=tool_msgs)

        # History: user + 4 tool messages + assistant = 6
        assert len(cm.history) == 6
        # On the next turn, the LLM should see all tool messages
        messages = cm.build_messages("sys", "what tools did you use?")
        # system + 6 history + new user = 8
        assert len(messages) == 8

    def test_empty_tool_messages_treated_as_none(self):
        """Empty tool_messages list behaves same as None."""
        cm = ConversationManager()
        cm.save_turn("hello", "hi", tool_messages=[])
        assert len(cm.history) == 2  # Just user + assistant, no extras
