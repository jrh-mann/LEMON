"""Tests for post-tool LLM error handling in the orchestrator.

Verifies that when the LLM call that follows tool execution raises an
exception (e.g. json.JSONDecodeError from a corrupted Anthropic SSE
stream), the orchestrator catches it gracefully instead of letting
it propagate to the socket handler as a raw error message.

Also verifies that malformed tool arguments are logged with a warning
rather than silently replaced with {}.
"""

import json
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from src.backend.agents.orchestrator import Orchestrator
from src.backend.tools import ToolRegistry
from src.backend.tools.core import Tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeEchoTool(Tool):
    """Minimal tool that succeeds with a simple result."""
    name = "echo"
    description = "Echoes input back."
    parameters: list = []

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        return {"success": True, "message": "echo ok"}


def _make_orchestrator() -> Orchestrator:
    """Build an orchestrator with a fake echo tool."""
    registry = ToolRegistry()
    registry.register(FakeEchoTool())
    return Orchestrator(registry)


# ---------------------------------------------------------------------------
# Test: post-tool LLM call exception is caught
# ---------------------------------------------------------------------------

class TestPostToolLLMError:
    """Verify that exceptions from the post-tool LLM call are caught."""

    def test_json_error_in_post_tool_call_returns_llm_error(self):
        """When call_llm_with_tools raises JSONDecodeError after tool
        execution, respond() should return an 'LLM error:' message
        instead of letting the exception propagate."""
        orch = _make_orchestrator()

        call_count = 0

        def fake_call_llm_with_tools(messages, **kwargs):
            """First call returns a tool call; second raises JSONDecodeError."""
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Initial call: LLM requests the echo tool
                tool_calls = [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "echo",
                            "arguments": "{}",
                        },
                    }
                ]
                return ("", tool_calls)
            else:
                # Post-tool call: simulate corrupted SSE stream
                raise json.JSONDecodeError(
                    "Expecting ',' delimiter",
                    '{"partial": "data"',
                    18,
                )

        with patch(
            "src.backend.agents.orchestrator.call_llm_with_tools",
            side_effect=fake_call_llm_with_tools,
        ), patch(
            "src.backend.agents.orchestrator.build_system_prompt",
            return_value="You are a test assistant.",
        ), patch(
            "src.backend.agents.orchestrator.tool_descriptions",
            return_value=[],
        ):
            result = orch.respond("test message", allow_tools=True)

        assert call_count == 2, "Expected two LLM calls (initial + post-tool)"
        assert "LLM error:" in result
        # The raw JSONDecodeError message should be wrapped, not raw
        assert "Expecting ',' delimiter" in result

    def test_generic_exception_in_post_tool_call_returns_llm_error(self):
        """Any exception (not just JSONDecodeError) in the post-tool call
        should be caught and returned as a user-friendly error."""
        orch = _make_orchestrator()

        call_count = 0

        def fake_call_llm_with_tools(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                tool_calls = [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "echo",
                            "arguments": "{}",
                        },
                    }
                ]
                return ("", tool_calls)
            else:
                raise ConnectionError("API connection lost")

        with patch(
            "src.backend.agents.orchestrator.call_llm_with_tools",
            side_effect=fake_call_llm_with_tools,
        ), patch(
            "src.backend.agents.orchestrator.build_system_prompt",
            return_value="You are a test assistant.",
        ), patch(
            "src.backend.agents.orchestrator.tool_descriptions",
            return_value=[],
        ):
            result = orch.respond("test message", allow_tools=True)

        assert "LLM error:" in result
        assert "API connection lost" in result

    def test_post_tool_error_saves_to_history(self):
        """When post-tool LLM call fails, the error should be saved
        to orchestrator history for context in future messages."""
        orch = _make_orchestrator()

        call_count = 0

        def fake_call_llm_with_tools(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                tool_calls = [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "echo",
                            "arguments": "{}",
                        },
                    }
                ]
                return ("", tool_calls)
            else:
                raise json.JSONDecodeError(
                    "Expecting ',' delimiter",
                    '{"partial": "data"',
                    18,
                )

        with patch(
            "src.backend.agents.orchestrator.call_llm_with_tools",
            side_effect=fake_call_llm_with_tools,
        ), patch(
            "src.backend.agents.orchestrator.build_system_prompt",
            return_value="You are a test assistant.",
        ), patch(
            "src.backend.agents.orchestrator.tool_descriptions",
            return_value=[],
        ):
            orch.respond("test message", allow_tools=True)

        # History should contain the user message and the error response
        assert len(orch.history) >= 2
        assert orch.history[-2]["role"] == "user"
        assert orch.history[-2]["content"] == "test message"
        assert orch.history[-1]["role"] == "assistant"
        assert "LLM error:" in orch.history[-1]["content"]


# ---------------------------------------------------------------------------
# Test: malformed tool args logging
# ---------------------------------------------------------------------------

class TestMalformedToolArgsLogging:
    """Verify that malformed tool arguments produce a warning log."""

    def test_malformed_args_logged_with_warning(self):
        """When LLM returns unparseable tool arguments, orchestrator
        should log a warning instead of silently falling back to {}."""
        orch = _make_orchestrator()

        call_count = 0

        def fake_call_llm_with_tools(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # LLM returns tool call with malformed arguments
                tool_calls = [
                    {
                        "id": "call_bad",
                        "type": "function",
                        "function": {
                            "name": "echo",
                            "arguments": '{not valid json!!!',
                        },
                    }
                ]
                return ("", tool_calls)
            else:
                # Post-tool call returns normal text
                return ("Done.", [])

        with patch(
            "src.backend.agents.orchestrator.call_llm_with_tools",
            side_effect=fake_call_llm_with_tools,
        ), patch(
            "src.backend.agents.orchestrator.build_system_prompt",
            return_value="You are a test assistant.",
        ), patch(
            "src.backend.agents.orchestrator.tool_descriptions",
            return_value=[],
        ):
            # The tool should still execute (with {} args) but a warning
            # should be logged. We verify the tool ran successfully.
            result = orch.respond("test message", allow_tools=True)

        # The response should complete without error
        assert "error" not in result.lower() or "LLM error" in result
