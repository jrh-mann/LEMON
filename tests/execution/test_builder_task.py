"""Tests for BuilderTask — lightweight subworkflow build task.

BuilderTask runs headless with its own EventSink, satisfies the
Registrable protocol for TaskRegistry, and supports resume via swap_sink.
"""

import queue as q

from src.backend.tasks.builder_task import BuilderTask
from src.backend.tasks.sse import EventSink
from src.backend.tasks.registry import TaskRegistry


class _OrchestratorStub:
    def __init__(self):
        self.current_workflow = {"nodes": [{"id": "n1"}], "edges": []}
        self.workflow_analysis = {"variables": [], "outputs": [], "output_type": "string"}


def _drain_events(sink: EventSink) -> list[tuple[str, dict]]:
    """Read all queued events from the sink without blocking."""
    events = []
    while True:
        try:
            item = sink._queue.get_nowait()
        except q.Empty:
            break
        if item is None:
            break
        events.append(item)
    return events


class TestBuilderTaskCallbacks:
    def test_stream_chunk_accumulates_and_emits(self):
        """stream_chunk accumulates in stream_buffer and emits chat_stream."""
        sink = EventSink()
        task = BuilderTask(sink=sink, workflow_id="wf_1", user_id="u1", task_id="t1")

        task.stream_chunk("Hello ")
        task.stream_chunk("world")

        assert task.stream_buffer == "Hello world"
        events = _drain_events(sink)
        assert len(events) == 2
        assert all(name == "chat_stream" for name, _ in events)
        assert events[0][1]["chunk"] == "Hello "
        assert events[1][1]["chunk"] == "world"

    def test_stream_thinking_accumulates_and_emits(self):
        """stream_thinking accumulates in thinking_chunks and emits chat_thinking."""
        sink = EventSink()
        task = BuilderTask(sink=sink, workflow_id="wf_1", user_id="u1", task_id="t1")

        task.stream_thinking("Let me think...")
        task.stream_thinking(" about this.")

        assert task.thinking_chunks == ["Let me think...", " about this."]
        events = _drain_events(sink)
        assert len(events) == 2
        assert all(name == "chat_thinking" for name, _ in events)

    def test_stream_chunk_skipped_when_cancelled(self):
        """stream_chunk is a no-op when task is cancelled."""
        sink = EventSink()
        task = BuilderTask(sink=sink, workflow_id="wf_1", user_id="u1", task_id="t1")

        task._cancelled = True
        task.stream_chunk("should not appear")

        assert task.stream_buffer == ""
        assert _drain_events(sink) == []

    def test_is_cancelled_detects_closed_sink(self):
        """is_cancelled returns True when the sink is closed (client disconnect)."""
        sink = EventSink()
        task = BuilderTask(sink=sink, workflow_id="wf_1", user_id="u1", task_id="t1")

        assert not task.is_cancelled()
        sink.close()
        assert task.is_cancelled()

    def test_emit_user_message(self):
        """emit_user_message pushes build_user_message event."""
        sink = EventSink()
        task = BuilderTask(sink=sink, workflow_id="wf_1", user_id="u1", task_id="t1")

        task.emit_user_message("Build a calculator")

        events = _drain_events(sink)
        assert len(events) == 1
        assert events[0][0] == "build_user_message"
        assert events[0][1]["content"] == "Build a calculator"
        assert events[0][1]["workflow_id"] == "wf_1"

    def test_emit_response_flushes_tool_summary(self):
        """emit_response flushes pending tool summaries before the final event."""
        sink = EventSink()
        task = BuilderTask(sink=sink, workflow_id="wf_1", user_id="u1", task_id="t1")

        task.tool_summary.note("add_node", success=True)
        task.emit_response("Done building")

        events = _drain_events(sink)
        event_names = [name for name, _ in events]
        # Should have chat_stream (flushed summary) then chat_response
        assert "chat_stream" in event_names
        assert "chat_response" in event_names
        # chat_response should be last
        assert event_names[-1] == "chat_response"
        assert events[-1][1]["response"] == "Done building"

    def test_workflow_id_auto_injected(self):
        """workflow_id is automatically added to event payloads."""
        sink = EventSink()
        task = BuilderTask(sink=sink, workflow_id="wf_42", user_id="u1", task_id="t1")

        task.emit_progress("Building...", event="start")

        events = _drain_events(sink)
        assert events[0][1]["workflow_id"] == "wf_42"


class TestBuilderTaskToolEvents:
    def test_tool_start_tracked(self):
        """on_tool_event('tool_start') records the tool call."""
        sink = EventSink()
        task = BuilderTask(sink=sink, workflow_id="wf_1", user_id="u1", task_id="t1")

        task.on_tool_event("tool_start", "add_node", {"type": "llm"}, None)

        assert len(task.executed_tools) == 1
        assert task.executed_tools[0]["tool"] == "add_node"
        assert task.executed_tools[0]["status"] == "running"

    def test_tool_complete_emits_workflow_update(self):
        """Successful edit tool emits workflow_update and workflow_state_updated."""
        sink = EventSink()
        task = BuilderTask(sink=sink, workflow_id="wf_1", user_id="u1", task_id="t1")
        task.orchestrator = _OrchestratorStub()

        task.on_tool_event(
            "tool_complete", "batch_edit_workflow", {},
            {"success": True, "action": "batch_edit", "workflow_id": "wf_1"},
        )

        events = _drain_events(sink)
        event_names = [name for name, _ in events]
        assert "workflow_update" in event_names
        assert "workflow_state_updated" in event_names

    def test_tool_complete_without_orchestrator_no_crash(self):
        """workflow_state_updated is skipped when orchestrator is not set."""
        sink = EventSink()
        task = BuilderTask(sink=sink, workflow_id="wf_1", user_id="u1", task_id="t1")

        task.on_tool_event(
            "tool_complete", "batch_edit_workflow", {},
            {"success": True, "action": "batch_edit", "workflow_id": "wf_1"},
        )

        events = _drain_events(sink)
        event_names = [name for name, _ in events]
        assert "workflow_update" in event_names
        assert "workflow_state_updated" not in event_names

    def test_tool_batch_complete_flushes_summary(self):
        """tool_batch_complete flushes accumulated tool summaries."""
        sink = EventSink()
        task = BuilderTask(sink=sink, workflow_id="wf_1", user_id="u1", task_id="t1")

        task.tool_summary.note("add_node", success=True)
        task.on_tool_event("tool_batch_complete", "", {}, None)

        events = _drain_events(sink)
        assert any(name == "chat_stream" for name, _ in events)


class TestBuilderTaskResume:
    def test_swap_sink_replays_content(self):
        """swap_sink replays thinking + stream to the new sink."""
        old_sink = EventSink()
        task = BuilderTask(sink=old_sink, workflow_id="wf_1", user_id="u1", task_id="t1")

        # Accumulate content
        task.stream_thinking("thinking...")
        task.stream_chunk("partial response")
        _drain_events(old_sink)  # clear old events

        # Swap to new sink
        new_sink = EventSink()
        task.swap_sink(new_sink)

        assert task.sink is new_sink
        assert old_sink.is_closed

        events = _drain_events(new_sink)
        event_names = [name for name, _ in events]
        assert "chat_progress" in event_names  # resumed
        assert "chat_thinking" in event_names
        assert "chat_stream" in event_names

        # Verify replayed content
        thinking_event = next(e for n, e in events if n == "chat_thinking")
        assert thinking_event["chunk"] == "thinking..."
        stream_event = next(e for n, e in events if n == "chat_stream")
        assert stream_event["chunk"] == "partial response"

    def test_swap_sink_replays_workflow_state(self):
        """swap_sink replays workflow state when orchestrator is attached."""
        old_sink = EventSink()
        task = BuilderTask(sink=old_sink, workflow_id="wf_1", user_id="u1", task_id="t1")
        task.orchestrator = _OrchestratorStub()

        new_sink = EventSink()
        task.swap_sink(new_sink)

        events = _drain_events(new_sink)
        event_names = [name for name, _ in events]
        assert "workflow_state_updated" in event_names


class TestBuilderTaskRegistry:
    def test_registrable_fields(self):
        """BuilderTask satisfies the Registrable protocol."""
        sink = EventSink()
        task = BuilderTask(sink=sink, workflow_id="wf_1", user_id="u1", task_id="t1")

        # Registrable protocol fields
        assert task.task_id == "t1"
        assert task.user_id == "u1"
        assert task.current_workflow_id == "wf_1"
        assert task._cancelled is False
        assert task._notified is False
        assert isinstance(task._created_at, float)

    def test_register_and_lookup(self):
        """BuilderTask can be registered and found by workflow_id."""
        registry = TaskRegistry()
        sink = EventSink()
        task = BuilderTask(sink=sink, workflow_id="wf_1", user_id="u1", task_id="t1")

        registry.register(task)

        assert registry.get("t1") is task
        assert registry.get_by_workflow("u1", "wf_1") is task

        registry.unregister(task)
        assert registry.get("t1") is None

    def test_cancel_via_registry(self):
        """Registry cancel sets the _cancelled flag."""
        registry = TaskRegistry()
        sink = EventSink()
        task = BuilderTask(sink=sink, workflow_id="wf_1", user_id="u1", task_id="t1")

        registry.register(task)
        registry.cancel("t1")

        assert task._cancelled is True
        assert task.is_cancelled()
