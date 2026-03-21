"""Tests for the event bus and its integration with the orchestrator."""

import pytest
from typing import Any, Dict, List, Tuple

from src.backend.events.bus import EventBus
from src.backend.events.types import (
    TOOL_STARTED,
    TOOL_COMPLETED,
    TOOL_BATCH_COMPLETE,
    WORKFLOW_UPDATED,
)
from src.backend.tools.core import Tool, ToolParameter, ToolRegistry
from src.backend.agents.orchestrator import Orchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _EchoTool(Tool):
    """Trivial tool that echoes its args back — used by orchestrator tests."""
    name = "echo"
    description = "Returns args as-is."
    parameters = [ToolParameter(name="msg", type="string", description="message")]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        return {"success": True, "message": args.get("msg", "")}


def _make_registry() -> ToolRegistry:
    """Create a ToolRegistry with just the echo tool registered."""
    reg = ToolRegistry()
    reg.register(_EchoTool())
    return reg


# ---------------------------------------------------------------------------
# Unit tests — EventBus in isolation
# ---------------------------------------------------------------------------

class TestEventBusUnit:

    def test_subscribe_and_emit(self) -> None:
        """Subscribing to an event and emitting it calls the callback."""
        bus = EventBus()
        received: List[Tuple[str, Dict[str, Any]]] = []

        bus.subscribe(TOOL_STARTED, lambda et, p: received.append((et, p)))
        bus.emit(TOOL_STARTED, {"tool": "add_node"})

        assert len(received) == 1
        assert received[0][0] == TOOL_STARTED
        assert received[0][1]["tool"] == "add_node"

    def test_subscribe_only_receives_matching_events(self) -> None:
        """A type-specific subscriber does not receive other event types."""
        bus = EventBus()
        received: List[str] = []

        bus.subscribe(TOOL_STARTED, lambda et, _p: received.append(et))
        bus.emit(TOOL_COMPLETED, {"tool": "x", "result": {}, "success": True, "args": {}})

        assert received == []

    def test_global_subscriber(self) -> None:
        """Global subscribers receive all events."""
        bus = EventBus()
        received: List[str] = []

        bus.subscribe_all(lambda et, _p: received.append(et))
        bus.emit(TOOL_STARTED, {"tool": "a"})
        bus.emit(TOOL_COMPLETED, {"tool": "b", "result": {}, "success": True, "args": {}})
        bus.emit(WORKFLOW_UPDATED, {"workflow": {}})

        assert received == [TOOL_STARTED, TOOL_COMPLETED, WORKFLOW_UPDATED]

    def test_subscriber_error_doesnt_crash(self) -> None:
        """A failing subscriber doesn't prevent other subscribers from being called."""
        bus = EventBus()
        received: List[str] = []

        def _bad_subscriber(_et: str, _p: Dict[str, Any]) -> None:
            raise RuntimeError("boom")

        # Register a bad subscriber, then a good one
        bus.subscribe(TOOL_STARTED, _bad_subscriber)
        bus.subscribe(TOOL_STARTED, lambda et, _p: received.append(et))

        # Should not raise — the error is caught and logged
        bus.emit(TOOL_STARTED, {"tool": "x"})

        # The second subscriber still ran
        assert received == [TOOL_STARTED]

    def test_global_subscriber_error_doesnt_crash(self) -> None:
        """A failing global subscriber doesn't block other global subscribers."""
        bus = EventBus()
        received: List[str] = []

        bus.subscribe_all(lambda _et, _p: (_ for _ in ()).throw(ValueError("oops")))
        bus.subscribe_all(lambda et, _p: received.append(et))

        bus.emit(TOOL_STARTED, {"tool": "x"})
        assert received == [TOOL_STARTED]

    def test_clear_removes_all_subscribers(self) -> None:
        """After clear(), no subscribers remain."""
        bus = EventBus()
        received: List[str] = []

        bus.subscribe(TOOL_STARTED, lambda et, _p: received.append(et))
        bus.subscribe_all(lambda et, _p: received.append(et))
        bus.clear()
        bus.emit(TOOL_STARTED, {"tool": "x"})

        assert received == []


# ---------------------------------------------------------------------------
# Integration tests — Orchestrator emits events via its EventBus
# ---------------------------------------------------------------------------

class TestOrchestratorEventBus:

    def test_orchestrator_has_default_event_bus(self) -> None:
        """Orchestrator creates its own EventBus when none is injected."""
        orch = Orchestrator(_make_registry())
        assert isinstance(orch.event_bus, EventBus)

    def test_orchestrator_accepts_injected_event_bus(self) -> None:
        """Orchestrator uses an injected EventBus instead of creating one."""
        bus = EventBus()
        orch = Orchestrator(_make_registry(), event_bus=bus)
        assert orch.event_bus is bus

    def test_orchestrator_emits_tool_events(self) -> None:
        """When orchestrator runs a tool, TOOL_STARTED and TOOL_COMPLETED are emitted."""
        bus = EventBus()
        orch = Orchestrator(_make_registry(), event_bus=bus)

        events: List[Tuple[str, Dict[str, Any]]] = []
        bus.subscribe_all(lambda et, p: events.append((et, p)))

        result = orch.run_tool("echo", {"msg": "hello"})

        assert result.success is True

        # Should have exactly 2 events: TOOL_STARTED then TOOL_COMPLETED
        event_types = [e[0] for e in events]
        assert event_types == [TOOL_STARTED, TOOL_COMPLETED]

        # Validate TOOL_STARTED payload
        started_payload = events[0][1]
        assert started_payload["tool"] == "echo"
        assert started_payload["args"] == {"msg": "hello"}

        # Validate TOOL_COMPLETED payload
        completed_payload = events[1][1]
        assert completed_payload["tool"] == "echo"
        assert completed_payload["success"] is True
        assert completed_payload["result"]["message"] == "hello"

    def test_orchestrator_emits_events_on_tool_failure(self) -> None:
        """TOOL_COMPLETED carries success=False when the tool fails."""
        bus = EventBus()
        orch = Orchestrator(_make_registry(), event_bus=bus)

        events: List[Tuple[str, Dict[str, Any]]] = []
        bus.subscribe(TOOL_COMPLETED, lambda et, p: events.append((et, p)))

        # "unknown_tool" is not registered so run_tool will raise/return failure
        # but we need a tool that actually returns success=False — let's use a
        # tool with a missing required field that the echo tool will still handle.
        # Actually, calling an unknown tool raises ValueError which is caught by
        # _normalize_tool_result. Let's register a tool that explicitly fails.
        class _FailTool(Tool):
            name = "fail_tool"
            description = "Always fails."
            parameters: list = []
            def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
                return {"success": False, "error": "deliberate failure"}

        orch.tools.register(_FailTool())
        orch.run_tool("fail_tool", {})

        assert len(events) == 1
        assert events[0][1]["success"] is False
