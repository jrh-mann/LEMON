from src.backend.api.builder_callbacks import BackgroundBuilderCallbacks


class _RegistryStub:
    def __init__(self):
        self.events = []

    def send_to_sync(self, conn_id, event, payload):
        self.events.append((conn_id, event, payload))


class _OrchestratorStub:
    def __init__(self):
        self.current_workflow = {"nodes": [{"id": "n1"}], "edges": []}
        self.workflow_analysis = {"variables": [], "outputs": [], "output_type": "string"}


def test_background_builder_callbacks_emit_workflow_state_when_orchestrator_attached():
    registry = _RegistryStub()
    cb = BackgroundBuilderCallbacks(registry, "conn_1", "wf_1", orchestrator=_OrchestratorStub())

    cb.on_tool_event(
        "tool_complete",
        "batch_edit_workflow",
        {},
        {"success": True, "action": "batch_edit", "workflow_id": "wf_1"},
    )

    event_names = [event for _, event, _ in registry.events]
    assert "workflow_update" in event_names
    assert "workflow_state_updated" in event_names


def test_background_builder_callbacks_do_not_crash_without_orchestrator():
    registry = _RegistryStub()
    cb = BackgroundBuilderCallbacks(registry, "conn_1", "wf_1")

    cb.on_tool_event(
        "tool_complete",
        "batch_edit_workflow",
        {},
        {"success": True, "action": "batch_edit", "workflow_id": "wf_1"},
    )

    event_names = [event for _, event, _ in registry.events]
    assert "workflow_update" in event_names
    assert "workflow_state_updated" not in event_names
