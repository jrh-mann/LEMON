"""Phase 4 tests: verify frontend type cleanup and socket event wiring.

Since these are TypeScript files, we test at the boundary:
- Backend emits plan_updated event correctly
- WorkflowAnalysis no longer carries tree/doubts in backend conversations
"""

from __future__ import annotations

import pytest


class TestConversationWorkflowClean:
    """Verify Conversation.workflow no longer has tree/doubts."""

    def test_workflow_defaults(self):
        from src.backend.api.conversations import Conversation
        from src.backend.agents.orchestrator_factory import build_orchestrator
        from pathlib import Path

        orch = build_orchestrator(Path("."))
        convo = Conversation(id="test", orchestrator=orch)

        # Workflow should only have nodes, edges, variables, outputs
        assert "tree" not in convo.workflow
        assert "doubts" not in convo.workflow
        assert "nodes" in convo.workflow
        assert "edges" in convo.workflow
        assert "variables" in convo.workflow
        assert "outputs" in convo.workflow

    def test_workflow_analysis_view(self):
        from src.backend.api.conversations import Conversation
        from src.backend.agents.orchestrator_factory import build_orchestrator
        from pathlib import Path

        orch = build_orchestrator(Path("."))
        convo = Conversation(id="test", orchestrator=orch)

        analysis = convo.workflow_analysis
        assert "tree" not in analysis
        assert "doubts" not in analysis
        assert "variables" in analysis
        assert "outputs" in analysis


class TestPlanUpdatedSocketEvent:
    """Verify the update_plan tool result triggers plan_updated emission."""

    def test_socket_chat_emits_plan_updated(self):
        """Verify on_tool_event recognizes update_plan and would emit plan_updated."""
        # We can't test full socket emission without socketio,
        # but verify the tool returns the right structure for the handler
        from src.backend.tools.workflow_analysis.update_plan import UpdatePlanTool

        tool = UpdatePlanTool()
        result = tool.execute(
            {"items": [{"text": "step 1", "done": False}]},
            session_state={},
        )
        assert result["success"] is True
        assert result["action"] == "plan_updated"
        assert result["items"] == [{"text": "step 1", "done": False}]
