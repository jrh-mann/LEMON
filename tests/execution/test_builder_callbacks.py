"""Tests for BackgroundBuilderCallbacks with EventSink."""

from src.backend.api.builder_callbacks import BackgroundBuilderCallbacks
from src.backend.api.sse import EventSink


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
        except Exception:
            break
        if item is None:
            break
        events.append(item)
    return events


def test_background_builder_callbacks_emit_workflow_state_when_orchestrator_attached():
    sink = EventSink()
    cb = BackgroundBuilderCallbacks(sink, "wf_1", orchestrator=_OrchestratorStub())

    cb.on_tool_event(
        "tool_complete",
        "batch_edit_workflow",
        {},
        {"success": True, "action": "batch_edit", "workflow_id": "wf_1"},
    )

    events = _drain_events(sink)
    event_names = [name for name, _ in events]
    assert "workflow_update" in event_names
    assert "workflow_state_updated" in event_names


def test_background_builder_callbacks_do_not_crash_without_orchestrator():
    sink = EventSink()
    cb = BackgroundBuilderCallbacks(sink, "wf_1")

    cb.on_tool_event(
        "tool_complete",
        "batch_edit_workflow",
        {},
        {"success": True, "action": "batch_edit", "workflow_id": "wf_1"},
    )

    events = _drain_events(sink)
    event_names = [name for name, _ in events]
    assert "workflow_update" in event_names
    # Without an orchestrator, workflow_state_updated should not be emitted
    assert "workflow_state_updated" not in event_names
