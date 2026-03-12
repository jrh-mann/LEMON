"""Tests for ConversationManager tool message persistence.

Verifies that tool-use and tool-result messages are preserved in history
between turns, so the LLM has context about previously executed tools.
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.backend.agents.conversation_manager import ConversationManager
from src.backend.agents.orchestrator_factory import build_orchestrator
from src.backend.agents.turn import Turn
from src.backend.llm.client import LLMResponse


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
                {"id": "tc_1", "name": "list_workflows", "input": {}}
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
                {"id": "tc_1", "name": "add_node", "input": {"type": "start"}}
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
                {"id": "tc_1", "name": "list_workflows", "input": {}}
            ]},
            {"role": "tool", "tool_call_id": "tc_1", "content": '{"count": 0}'},
            # Round 2: create subworkflow
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "tc_2", "name": "create_subworkflow", "input": {"name": "BMI"}}
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


@pytest.fixture
def repo_root():
    return Path(__file__).resolve().parent.parent


class TestOrchestratorToolHistoryIntegration:
    """Integration test: orchestrator.respond() with mocked LLM preserves tool messages."""

    def test_tool_calls_preserved_in_history_after_respond(self, repo_root):
        """After a turn with tool calls, history contains tool-use and tool-result messages."""
        orch = build_orchestrator(repo_root)

        # Mock call_llm to simulate: LLM requests get_current_workflow, gets result, then responds
        call_count = 0
        def fake_call_llm(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: LLM wants to use get_current_workflow
                return LLMResponse(
                    text="",
                    tool_calls=[{
                        "id": "tc_001",
                        "name": "get_current_workflow",
                        "input": {},
                    }],
                    usage={"input_tokens": 1000},
                )
            else:
                # Second call: LLM responds with text (no more tool calls)
                return LLMResponse(
                    text="The workflow is currently empty.",
                    tool_calls=[],
                    usage={"input_tokens": 1500},
                )

        with patch("src.backend.agents.orchestrator.call_llm", side_effect=fake_call_llm):
            turn = Turn("Show me the current workflow", "test")
            turn.start()
            result = orch.respond("Show me the current workflow", turn=turn, allow_tools=True)
            turn.complete(result)
            turn.commit(orch.conversation)

        assert "empty" in result.lower()

        # The key assertion: history must contain tool-use and tool-result messages
        history = orch.conversation.history
        roles = [m["role"] for m in history]
        assert roles == ["user", "assistant", "tool", "assistant"], (
            f"Expected [user, assistant(tool_use), tool(result), assistant(final)] "
            f"but got {roles}"
        )
        # Verify the assistant message has tool_calls
        assert "tool_calls" in history[1], "Second message should be assistant with tool_calls"
        assert history[1]["tool_calls"][0]["name"] == "get_current_workflow"
        # Verify the tool result message
        assert history[2]["role"] == "tool"
        assert history[2]["tool_call_id"] == "tc_001"
        # Verify final assistant text
        assert history[3]["role"] == "assistant"
        assert "empty" in history[3]["content"].lower()

    def test_second_turn_sees_first_turn_tool_calls(self, repo_root):
        """On the second turn, the LLM receives messages containing tool calls from the first turn."""
        orch = build_orchestrator(repo_root)

        call_count = 0
        captured_messages = []

        def fake_call_llm(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            # Capture messages sent to the LLM on each call
            captured_messages.append(list(messages))

            if call_count == 1:
                # Turn 1: LLM uses add_node
                return LLMResponse(
                    text="",
                    tool_calls=[{
                        "id": "tc_add",
                        "name": "get_current_workflow",
                        "input": {},
                    }],
                    usage={"input_tokens": 1000},
                )
            elif call_count == 2:
                # Turn 1: LLM responds after tool result
                return LLMResponse(
                    text="I checked the workflow.",
                    tool_calls=[],
                    usage={"input_tokens": 1500},
                )
            else:
                # Turn 2: LLM responds (should see tool history in messages)
                return LLMResponse(
                    text="Yes, I already checked it.",
                    tool_calls=[],
                    usage={"input_tokens": 2000},
                )

        with patch("src.backend.agents.orchestrator.call_llm", side_effect=fake_call_llm):
            turn1 = Turn("Check the workflow", "test")
            turn1.start()
            r1 = orch.respond("Check the workflow", turn=turn1, allow_tools=True)
            turn1.complete(r1)
            turn1.commit(orch.conversation)

            turn2 = Turn("Did you already check it?", "test")
            turn2.start()
            r2 = orch.respond("Did you already check it?", turn=turn2, allow_tools=True)
            turn2.complete(r2)
            turn2.commit(orch.conversation)

        # The third call_llm invocation (turn 2) should contain tool messages from turn 1
        turn2_messages = captured_messages[2]
        # Filter out system prompt — look at history + new user message
        non_system = [m for m in turn2_messages if m["role"] != "system"]
        roles = [m["role"] for m in non_system]
        # Expected: user(turn1), assistant(tool_use), tool(result), assistant(final),
        #           user(turn2)
        assert roles == ["user", "assistant", "tool", "assistant", "user"], (
            f"Turn 2 messages should include tool history from turn 1, got roles: {roles}"
        )
        # The assistant message with tool_calls should reference get_current_workflow
        tool_use_msg = non_system[1]
        assert "tool_calls" in tool_use_msg
        assert tool_use_msg["tool_calls"][0]["name"] == "get_current_workflow"
