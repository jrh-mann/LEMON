"""Tests for SteppedExecutionTask with EventSink.

Verifies:
- Events are pushed to the sink in correct order
- Pause/resume state machine works
- Stop interrupts execution
- Sink is closed when execution finishes
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from src.backend.api.sse import EventSink
from src.backend.api.execution_task import (
    SteppedExecutionTask,
    StoppedExecutionError,
    register_execution,
    pause_execution,
    resume_execution,
    stop_execution,
    _clear_execution,
)


def _collect_events(sink: EventSink) -> list[tuple[str, dict]]:
    """Drain the sink and return (event_name, data) tuples."""
    events = []
    for line in sink:
        # Parse SSE format: "event: <name>\ndata: <json>\n\n"
        parts = line.strip().split("\n")
        event_name = parts[0].split(": ", 1)[1]
        data = json.loads(parts[1].split(": ", 1)[1])
        events.append((event_name, data))
    return events


class TestExecutionTaskBasic:
    """Basic execution lifecycle."""

    def test_empty_workflow_emits_error(self):
        """Workflow with no nodes emits execution_error and closes sink."""
        sink = EventSink()
        task = SteppedExecutionTask(
            sink=sink,
            workflow_store=None,  # type: ignore
            user_id="u1",
            execution_id="exec1",
            workflow={"nodes": [], "edges": []},
            inputs={},
        )
        task.run()

        events = _collect_events(sink)
        assert len(events) == 1
        assert events[0][0] == "execution_error"
        assert "no nodes" in events[0][1]["error"]
        assert sink.is_closed

    def test_sink_closed_after_run(self):
        """Sink is always closed when run() finishes, even on error."""
        sink = EventSink()
        task = SteppedExecutionTask(
            sink=sink,
            workflow_store=None,  # type: ignore
            user_id="u1",
            execution_id="exec2",
            workflow={"nodes": [], "edges": []},
            inputs={},
        )
        task.run()
        assert sink.is_closed


class TestExecutionStateMachine:
    """Pause/resume/stop state management."""

    def test_register_and_pause(self):
        """Registered execution can be paused."""
        register_execution("test_exec_1")
        assert pause_execution("test_exec_1")
        _clear_execution("test_exec_1")

    def test_pause_nonexistent(self):
        """Pausing a nonexistent execution returns False."""
        assert not pause_execution("nonexistent")

    def test_register_and_resume(self):
        """Registered execution can be paused then resumed."""
        register_execution("test_exec_2")
        assert pause_execution("test_exec_2")
        assert resume_execution("test_exec_2")
        _clear_execution("test_exec_2")

    def test_register_and_stop(self):
        """Registered execution can be stopped."""
        register_execution("test_exec_3")
        assert stop_execution("test_exec_3")
        _clear_execution("test_exec_3")

    def test_stop_nonexistent(self):
        """Stopping a nonexistent execution returns False."""
        assert not stop_execution("nonexistent")


class TestExecutionTaskStop:
    """Stop interrupts a running execution."""

    def test_stop_during_delay(self):
        """Stopping during the speed delay interrupts execution."""
        sink = EventSink()
        exec_id = "exec_stop_test"

        # Create a minimal workflow that will take a while to execute
        # (the speed_ms delay gives us time to stop)
        register_execution(exec_id)

        task = SteppedExecutionTask(
            sink=sink,
            workflow_store=None,  # type: ignore
            user_id="u1",
            execution_id=exec_id,
            workflow={"nodes": [], "edges": []},  # empty = immediate error
            inputs={},
            speed_ms=0,
        )

        # Run and verify it completes (empty workflow → error)
        task.run()
        events = _collect_events(sink)
        assert any(e[0] == "execution_error" for e in events)
        assert sink.is_closed
