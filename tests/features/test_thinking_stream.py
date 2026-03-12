"""Tests for real-time thinking stream pipeline — LLM extended thinking chunks
forwarded through orchestrator to socket events.

Covers:
1. on_thinking callback receives chunks from tool execution
2. Orchestrator run_tool() forwards thinking via on_tool_event("tool_thinking")
3. SocketChatTask.on_tool_event skips thinking for non-relevant events
"""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from src.backend.agents.orchestrator import Orchestrator
from src.backend.llm.client import LLMResponse
from src.backend.tools import ToolRegistry
from src.backend.tools.core import Tool, ToolParameter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeThinkingTool(Tool):
    """Minimal tool that invokes on_thinking to simulate extended thinking."""
    name = "fake_thinking_tool"
    description = "Fake tool for testing thinking stream."
    parameters: list = []

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        on_thinking = kwargs.get("on_thinking")
        # Simulate LLM sending thinking chunks
        for chunk in ["Examining ", "the diagram ", "structure..."]:
            if on_thinking:
                on_thinking(chunk)
        return {"success": True}


def _make_orchestrator_with_fake_tool() -> Orchestrator:
    """Build an orchestrator with a fake thinking tool."""
    registry = ToolRegistry()
    registry.register(FakeThinkingTool())
    return Orchestrator(registry)


# ---------------------------------------------------------------------------
# Test: on_thinking kwarg flows through ToolRegistry.execute -> Tool.execute
# ---------------------------------------------------------------------------

class TestToolReceivesOnThinking:
    """Verify on_thinking callback reaches the tool's execute method."""

    def test_on_thinking_kwarg_passed_to_tool(self):
        """ToolRegistry.execute should forward on_thinking to Tool.execute."""
        registry = ToolRegistry()
        registry.register(FakeThinkingTool())

        received_chunks: List[str] = []

        def capture(chunk: str) -> None:
            received_chunks.append(chunk)

        registry.execute(
            "fake_thinking_tool", {}, on_thinking=capture, session_state={},
        )

        assert received_chunks == ["Examining ", "the diagram ", "structure..."]


# ---------------------------------------------------------------------------
# Test: Orchestrator.run_tool forwards thinking via on_tool_event
# ---------------------------------------------------------------------------

class TestOrchestratorThinkingForwarding:
    """Verify run_tool creates an _on_thinking callback that fires tool events."""

    def test_run_tool_forwards_thinking(self):
        """run_tool with on_thinking should invoke the callback for each chunk."""
        orch = _make_orchestrator_with_fake_tool()

        received_chunks: List[str] = []

        def capture(chunk: str) -> None:
            received_chunks.append(chunk)

        result = orch.run_tool(
            "fake_thinking_tool", {}, on_thinking=capture,
        )

        assert result.success
        assert received_chunks == ["Examining ", "the diagram ", "structure..."]

    def test_respond_emits_tool_thinking_events(self):
        """Orchestrator.respond should emit tool_thinking events when tool runs."""
        orch = _make_orchestrator_with_fake_tool()

        tool_events: List[tuple] = []

        def capture_event(event: str, tool: str, args: Dict, result: Any) -> None:
            tool_events.append((event, tool, args, result))

        # Patch LLM calls so orchestrator invokes analyze_workflow tool
        fake_tool_call = {
            "id": "call_1",
            "name": "fake_thinking_tool",
            "input": {},
        }
        # First LLM call returns a tool call; second returns final text
        with patch("src.backend.agents.orchestrator.call_llm") as mock_llm:
            mock_llm.side_effect = [
                LLMResponse(text="", tool_calls=[fake_tool_call]),
                LLMResponse(text="Analysis complete."),
            ]
            orch.respond(
                "Analyze the workflow",
                stream=None,
                allow_tools=True,
                on_tool_event=capture_event,
            )

        # Filter to only tool_thinking events
        thinking_events = [
            (ev, tool, args)
            for ev, tool, args, _ in tool_events
            if ev == "tool_thinking"
        ]

        assert len(thinking_events) == 3
        assert thinking_events[0] == ("tool_thinking", "fake_thinking_tool", {"chunk": "Examining "})
        assert thinking_events[1] == ("tool_thinking", "fake_thinking_tool", {"chunk": "the diagram "})
        assert thinking_events[2] == ("tool_thinking", "fake_thinking_tool", {"chunk": "structure..."})

    def test_post_tool_llm_calls_suppress_thinking_stream(self):
        """Post-tool LLM calls should NOT stream thinking to the frontend.

        With adaptive thinking on Opus 4.6, interleaved thinking from
        multiple LLM calls in the tool loop would accumulate in the
        frontend's reasoning section, mixing initial reasoning with
        internal tool-result analysis. Only the initial call streams thinking.
        """
        orch = _make_orchestrator_with_fake_tool()

        thinking_chunks: List[str] = []

        def capture_thinking(chunk: str) -> None:
            thinking_chunks.append(chunk)

        fake_tool_call = {
            "id": "call_1",
            "name": "fake_thinking_tool",
            "input": {},
        }

        with patch("src.backend.agents.orchestrator.call_llm") as mock_llm:
            mock_llm.side_effect = [
                LLMResponse(text="", tool_calls=[fake_tool_call]),
                LLMResponse(text="Done."),
            ]
            orch.respond(
                "Do something",
                stream=lambda c: None,
                allow_tools=True,
                thinking=True,
                on_thinking=capture_thinking,
            )

        # Post-tool call should have on_thinking=None
        assert mock_llm.call_count == 2
        _, initial_kwargs = mock_llm.call_args_list[0]
        _, post_tool_kwargs = mock_llm.call_args_list[1]
        assert initial_kwargs["on_thinking"] is capture_thinking
        assert post_tool_kwargs["on_thinking"] is None


# ---------------------------------------------------------------------------
# Test: SocketChatTask.on_tool_event emits chat_thinking socket events
# ---------------------------------------------------------------------------

class TestWsChatThinkingEmission:
    """Verify on_tool_event('tool_thinking', ...) emits chat_thinking over SSE."""

    def _make_task(self) -> Any:
        """Build a minimal ChatTask with a mock EventSink."""
        from src.backend.api.chat_task import ChatTask
        from src.backend.api.sse import EventSink

        mock_sink = MagicMock(spec=EventSink)
        mock_sink.is_closed = False
        mock_convo_store = MagicMock()
        task = ChatTask(
            sink=mock_sink,
            conversation_store=mock_convo_store,
            repo_root=Path("/tmp"),
            workflow_store=MagicMock(),
            user_id="test_user",
            task_id="task_123",
            message="test",
            conversation_id="conv_1",
            files_data=[],
            workflow=None,
            analysis=None,
        )
        return task

    def test_skips_when_cancelled(self):
        """tool events should not emit if the task is cancelled."""
        task = self._make_task()

        # Mock is_cancelled to return True
        with patch.object(task, "is_cancelled", return_value=True):
            task.on_tool_event("tool_complete", "add_node", {}, {"success": True})

        task.sink.push.assert_not_called()

