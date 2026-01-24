"""Tests for ValidateWorkflowTool."""

import pytest
from src.backend.tools.validate_workflow import ValidateWorkflowTool

class TestValidateWorkflowTool:
    def setup_method(self):
        self.tool = ValidateWorkflowTool()

    def test_validate_valid_workflow(self):
        """Should return valid=True for a complete connected workflow"""
        workflow = {
            "nodes": [
                {"id": "n1", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "n2", "type": "end", "label": "End", "x": 100, "y": 0},
            ],
            "edges": [
                {"id": "e1", "from": "n1", "to": "n2", "label": ""}
            ],
        }
        session_state = {"current_workflow": workflow}
        
        result = self.tool.execute({}, session_state=session_state)
        
        assert result["success"] is True
        assert result["valid"] is True
        assert "message" in result

    def test_validate_disconnected_workflow(self):
        """Should return valid=False for disconnected workflow (unreachable node)"""
        workflow = {
            "nodes": [
                {"id": "n1", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "n2", "type": "end", "label": "End", "x": 100, "y": 0},
                {"id": "n3", "type": "process", "label": "Isolated", "x": 50, "y": 50},
            ],
            "edges": [
                {"id": "e1", "from": "n1", "to": "n2", "label": ""}
            ],
        }
        session_state = {"current_workflow": workflow}
        
        result = self.tool.execute({}, session_state=session_state)
        
        assert result["success"] is True
        assert result["valid"] is False
        assert len(result["errors"]) > 0
        assert any(e["code"] == "UNREACHABLE_NODE" for e in result["errors"])
        assert "Isolated" in result["message"]

    def test_validate_incomplete_decision(self):
        """Should return valid=False for decision node with insufficient branches"""
        workflow = {
            "nodes": [
                {"id": "n1", "type": "decision", "label": "Check?", "x": 0, "y": 0},
            ],
            "edges": [],
        }
        session_state = {"current_workflow": workflow}
        
        result = self.tool.execute({}, session_state=session_state)
        
        assert result["success"] is True
        assert result["valid"] is False
        assert any(e["code"] == "DECISION_NEEDS_BRANCHES" for e in result["errors"])
