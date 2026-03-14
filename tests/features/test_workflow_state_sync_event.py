from pathlib import Path


def test_backend_emits_combined_workflow_state_event():
    # ChatTask delegates SSE transport to ChatEventChannel.
    # The event name lives in the channel; the payload is built in chat_task.py.
    channel_content = Path("src/backend/tasks/chat_event_channel.py").read_text(encoding="utf-8")
    task_content = Path("src/backend/tasks/chat_task.py").read_text(encoding="utf-8")
    assert "workflow_state_updated" in channel_content
    assert '"workflow": self.convo.orchestrator.current_workflow' in task_content
    assert '"analysis": self.convo.orchestrator.workflow_analysis' in task_content


def test_frontend_registers_combined_workflow_state_handler():
    content = Path("src/frontend/src/api/streamActions.ts").read_text(encoding="utf-8")
    assert "workflow_state_updated" in content
    assert "setFlowchartSilent" in content
    assert "setAnalysis" in content


def test_frontend_guard_requires_workflow_id():
    """streamActions.ts drops workflow events that lack workflow_id."""
    content = Path("src/frontend/src/api/streamActions.ts").read_text(encoding="utf-8")
    # Both workflow_update and workflow_state_updated handlers must have the early-return guard
    assert "!data.workflow_id" in content or "!eventWfId" in content
    assert "workflow_update dropped: missing workflow_id" in content
    assert "workflow_state_updated dropped: missing workflow_id" in content


def test_workflow_page_sets_id_before_fetch():
    """WorkflowPage.tsx calls setCurrentWorkflowId before the async getWorkflow fetch."""
    content = Path("src/frontend/src/components/WorkflowPage.tsx").read_text(encoding="utf-8")
    set_id_pos = content.index("setCurrentWorkflowId(workflowId)")
    fetch_pos = content.index("await getWorkflow(workflowId)")
    assert set_id_pos < fetch_pos, "setCurrentWorkflowId must appear before getWorkflow"
