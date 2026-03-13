from pathlib import Path


def test_backend_emits_combined_workflow_state_event():
    # ChatTask delegates SSE transport to ChatEventChannel.
    # The event name lives in the channel; the payload is built in chat_task.py.
    channel_content = Path("src/backend/api/chat_event_channel.py").read_text(encoding="utf-8")
    task_content = Path("src/backend/api/chat_task.py").read_text(encoding="utf-8")
    assert "workflow_state_updated" in channel_content
    assert '"workflow": self.convo.orchestrator.current_workflow' in task_content
    assert '"analysis": self.convo.orchestrator.workflow_analysis' in task_content


def test_frontend_registers_combined_workflow_state_handler():
    content = Path("src/frontend/src/api/streamActions.ts").read_text(encoding="utf-8")
    assert "workflow_state_updated" in content
    assert "setFlowchartSilent" in content
    assert "setAnalysis" in content
