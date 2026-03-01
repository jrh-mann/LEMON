"""Tests for real-time thinking stream pipeline — LLM extended thinking chunks
forwarded from subagent through orchestrator to socket events.

Covers:
1. Subagent on_thinking callback receives chunks and still accumulates locally
2. Orchestrator run_tool() forwards thinking via on_tool_event("tool_thinking")
3. SocketChatTask.on_tool_event emits "chat_thinking" socket events
"""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from src.backend.agents.orchestrator import Orchestrator
from src.backend.tools import ToolRegistry
from src.backend.tools.core import Tool, ToolParameter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeAnalyzeTool(Tool):
    """Minimal tool that simulates analyze_workflow by invoking on_thinking."""
    name = "analyze_workflow"
    description = "Fake analyze tool for testing thinking stream."
    parameters: list = []

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        on_thinking = kwargs.get("on_thinking")
        # Simulate LLM sending thinking chunks
        for chunk in ["Examining ", "the diagram ", "structure..."]:
            if on_thinking:
                on_thinking(chunk)
        return {
            "success": True,
            "session_id": "test_session",
            "analysis": {
                "variables": [],
                "outputs": [],
                "tree": {},
                "doubts": [],
                "reasoning": "Examining the diagram structure...",
                "guidance": [],
            },
            "flowchart": {"nodes": [], "edges": []},
        }


def _make_orchestrator_with_fake_tool() -> Orchestrator:
    """Build an orchestrator with a fake analyze_workflow tool."""
    registry = ToolRegistry()
    registry.register(FakeAnalyzeTool())
    return Orchestrator(registry)


# ---------------------------------------------------------------------------
# Test: on_thinking kwarg flows through ToolRegistry.execute -> Tool.execute
# ---------------------------------------------------------------------------

class TestToolReceivesOnThinking:
    """Verify on_thinking callback reaches the tool's execute method."""

    def test_on_thinking_kwarg_passed_to_tool(self):
        """ToolRegistry.execute should forward on_thinking to Tool.execute."""
        registry = ToolRegistry()
        registry.register(FakeAnalyzeTool())

        received_chunks: List[str] = []

        def capture(chunk: str) -> None:
            received_chunks.append(chunk)

        registry.execute(
            "analyze_workflow", {}, on_thinking=capture, session_state={},
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
            "analyze_workflow", {}, on_thinking=capture,
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
            "function": {
                "name": "analyze_workflow",
                "arguments": "{}",
            },
        }
        # First LLM call returns a tool call; second returns final text
        with patch("src.backend.agents.orchestrator.call_llm_with_tools") as mock_llm:
            mock_llm.side_effect = [
                ("", [fake_tool_call]),  # Initial: request tool call
                ("Analysis complete.", []),  # Post-tool: final text
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
        assert thinking_events[0] == ("tool_thinking", "analyze_workflow", {"chunk": "Examining "})
        assert thinking_events[1] == ("tool_thinking", "analyze_workflow", {"chunk": "the diagram "})
        assert thinking_events[2] == ("tool_thinking", "analyze_workflow", {"chunk": "structure..."})


# ---------------------------------------------------------------------------
# Test: SocketChatTask.on_tool_event emits chat_thinking socket events
# ---------------------------------------------------------------------------

class TestSocketChatThinkingEmission:
    """Verify on_tool_event('tool_thinking', ...) emits chat_thinking over socket."""

    def _make_task(self) -> Any:
        """Build a minimal SocketChatTask with mocked socketio."""
        from src.backend.api.socket_chat import SocketChatTask

        mock_socketio = MagicMock()
        mock_convo_store = MagicMock()
        task = SocketChatTask(
            socketio=mock_socketio,
            conversation_store=mock_convo_store,
            repo_root=Path("/tmp"),
            workflow_store=MagicMock(),
            user_id="test_user",
            sid="test_sid",
            task_id="task_123",
            message="test",
            conversation_id="conv_1",
            files_data=[],
            workflow=None,
            analysis=None,
        )
        return task

    def test_emits_chat_thinking_on_tool_thinking_event(self):
        """tool_thinking event for analyze_workflow should emit chat_thinking."""
        task = self._make_task()

        task.on_tool_event("tool_thinking", "analyze_workflow", {"chunk": "Reasoning..."}, None)

        task.socketio.emit.assert_called_once_with(
            "chat_thinking",
            {"chunk": "Reasoning...", "task_id": "task_123"},
            to="test_sid",
        )

    def test_skips_empty_thinking_chunks(self):
        """Empty thinking chunks should not be emitted."""
        task = self._make_task()

        task.on_tool_event("tool_thinking", "analyze_workflow", {"chunk": ""}, None)

        task.socketio.emit.assert_not_called()

    def test_ignores_tool_thinking_for_other_tools(self):
        """tool_thinking for non-analyze tools should not emit chat_thinking."""
        task = self._make_task()

        task.on_tool_event("tool_thinking", "add_node", {"chunk": "thinking..."}, None)

        task.socketio.emit.assert_not_called()

    def test_skips_when_cancelled(self):
        """tool_thinking should not emit if the task is cancelled."""
        task = self._make_task()

        # Mock is_cancelled to return True
        with patch.object(task, "is_cancelled", return_value=True):
            task.on_tool_event("tool_thinking", "analyze_workflow", {"chunk": "data"}, None)

        task.socketio.emit.assert_not_called()


# ---------------------------------------------------------------------------
# Regression: reasoning field still populated after forwarding
# ---------------------------------------------------------------------------

class TestReasoningStillAccumulated:
    """Verify that forwarding chunks doesn't break local accumulation of reasoning."""

    def test_run_tool_still_stores_reasoning(self):
        """After run_tool with on_thinking, reasoning should still end up in orchestrator state."""
        orch = _make_orchestrator_with_fake_tool()

        orch.run_tool("analyze_workflow", {}, on_thinking=lambda _: None)

        # The fake tool returns reasoning in its analysis; orchestrator stores it
        assert orch.workflow.get("reasoning") == "Examining the diagram structure..."
