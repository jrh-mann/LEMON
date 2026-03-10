from pathlib import Path


def test_backend_emits_combined_workflow_state_event():
    content = Path("src/backend/api/ws_chat.py").read_text(encoding="utf-8")
    assert "workflow_state_updated" in content
    assert '"workflow": self.convo.orchestrator.current_workflow' in content
    assert '"analysis": self.convo.orchestrator.workflow_analysis' in content


def test_frontend_registers_combined_workflow_state_handler():
    content = Path("src/frontend/src/api/socket-handlers/workflowHandlers.ts").read_text(encoding="utf-8")
    assert "'workflow_state_updated'" in content
    assert "applyWorkflowStateUpdate" in content
    assert "setFlowchartSilent" in content
    assert "setAnalysis" in content
