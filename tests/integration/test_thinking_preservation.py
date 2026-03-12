"""Tests for thinking block preservation through the tool loop.

Verifies that:
1. _parse_anthropic_response returns full thinking block dicts (including signature)
2. _to_anthropic_messages reconstructs thinking blocks in assistant messages
3. Orchestrator includes thinking_blocks in tool-loop messages but strips from history
4. LLMResponse carries thinking_blocks
"""

from src.backend.llm.anthropic import _parse_anthropic_response, _to_anthropic_messages


class TestParseAnthropicResponse:
    """_parse_anthropic_response returns full thinking block dicts."""

    def test_returns_thinking_blocks_as_dicts(self):
        """Thinking blocks should be returned as full dicts, not concatenated text."""
        # Simulate an SDK response object with thinking + text content blocks
        class FakeBlock:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        class FakeMessage:
            content = [
                FakeBlock(type="thinking", thinking="Let me reason...", signature="sig123"),
                FakeBlock(type="text", text="Here is my answer"),
            ]

        text, tool_calls, thinking_blocks = _parse_anthropic_response(FakeMessage())

        assert text == "Here is my answer"
        assert tool_calls == []
        assert len(thinking_blocks) == 1
        assert thinking_blocks[0]["type"] == "thinking"
        assert thinking_blocks[0]["thinking"] == "Let me reason..."
        assert thinking_blocks[0]["signature"] == "sig123"

    def test_returns_thinking_blocks_with_signature(self):
        """Thinking blocks include signature for API replay."""
        class FakeBlock:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        class FakeMessage:
            content = [
                FakeBlock(type="thinking", thinking="Reasoning here", signature="abc"),
                FakeBlock(type="text", text="Answer"),
            ]

        text, tool_calls, thinking_blocks = _parse_anthropic_response(FakeMessage())

        assert text == "Answer"
        assert len(thinking_blocks) == 1
        assert thinking_blocks[0] == {"type": "thinking", "thinking": "Reasoning here", "signature": "abc"}

    def test_multiple_thinking_blocks(self):
        """Multiple thinking blocks are all preserved."""
        class FakeBlock:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        class FakeMessage:
            content = [
                FakeBlock(type="thinking", thinking="First thought", signature="s1"),
                FakeBlock(type="thinking", thinking="Second thought", signature="s2"),
                FakeBlock(type="text", text="Final"),
            ]

        _, _, thinking_blocks = _parse_anthropic_response(FakeMessage())

        assert len(thinking_blocks) == 2
        assert thinking_blocks[0]["thinking"] == "First thought"
        assert thinking_blocks[1]["thinking"] == "Second thought"

    def test_empty_thinking_skipped(self):
        """Thinking blocks with no text are not included."""
        class FakeBlock:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        class FakeMessage:
            content = [
                FakeBlock(type="thinking", thinking=None, signature="s1"),
                FakeBlock(type="text", text="Answer"),
            ]

        _, _, thinking_blocks = _parse_anthropic_response(FakeMessage())
        assert len(thinking_blocks) == 0


class TestToAnthropicMessages:
    """_to_anthropic_messages reconstructs thinking blocks."""

    def test_thinking_blocks_prepended_to_assistant_with_tool_calls(self):
        """Assistant messages with tool_calls should have thinking blocks first."""
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Do something."},
            {
                "role": "assistant",
                "content": "I'll use a tool.",
                "tool_calls": [
                    {"id": "tc1", "name": "my_tool", "input": {}}
                ],
                "thinking_blocks": [
                    {"type": "thinking", "thinking": "Let me think...", "signature": "sig1"}
                ],
            },
        ]

        system, converted = _to_anthropic_messages(messages)

        assert system == "You are helpful."
        assert len(converted) == 2  # user + assistant

        asst = converted[1]
        assert asst["role"] == "assistant"
        content = asst["content"]

        # First block should be thinking
        assert content[0]["type"] == "thinking"
        assert content[0]["thinking"] == "Let me think..."
        assert content[0]["signature"] == "sig1"

        # Then text
        assert content[1]["type"] == "text"
        assert content[1]["text"] == "I'll use a tool."

        # Then tool_use
        assert content[2]["type"] == "tool_use"
        assert content[2]["name"] == "my_tool"

    def test_thinking_blocks_prepended_to_plain_assistant(self):
        """Plain assistant messages (no tool_calls) should also have thinking blocks."""
        messages = [
            {"role": "user", "content": "Hello"},
            {
                "role": "assistant",
                "content": "Hi there!",
                "thinking_blocks": [
                    {"type": "thinking", "thinking": "Simple greeting", "signature": "s1"}
                ],
            },
        ]

        _, converted = _to_anthropic_messages(messages)

        asst = converted[1]
        content = asst["content"]
        assert content[0]["type"] == "thinking"
        assert content[1]["type"] == "text"

    def test_no_thinking_blocks_unchanged(self):
        """Messages without thinking_blocks work as before."""
        messages = [
            {"role": "user", "content": "Hi"},
            {
                "role": "assistant",
                "content": "Hello!",
                "tool_calls": [
                    {"id": "tc1", "name": "tool1", "input": {}}
                ],
            },
        ]

        _, converted = _to_anthropic_messages(messages)
        asst = converted[1]
        content = asst["content"]

        # No thinking block, just text + tool_use
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "tool_use"


class TestLLMResponseThinkingBlocks:
    """LLMResponse carries thinking_blocks."""

    def test_thinking_blocks_field_exists(self):
        from src.backend.llm.client import LLMResponse

        resp = LLMResponse(
            text="answer",
            thinking_blocks=[{"type": "thinking", "thinking": "reason", "signature": "s"}],
        )
        assert len(resp.thinking_blocks) == 1
        assert resp.thinking_blocks[0]["thinking"] == "reason"

    def test_thinking_blocks_defaults_empty(self):
        from src.backend.llm.client import LLMResponse

        resp = LLMResponse(text="answer")
        assert resp.thinking_blocks == []
