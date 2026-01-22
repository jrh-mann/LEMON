"""Tests for BatchEditWorkflowTool validation logic"""

import pytest
from src.backend.tools.workflow_edit.batch_edit import BatchEditWorkflowTool

class TestBatchEditValidation:
    """Test validation in BatchEditWorkflowTool"""

    def setup_method(self):
        self.tool = BatchEditWorkflowTool()

    def test_batch_add_decision_with_invalid_input(self):
        """Should reject batch operation referencing unregistered input"""
        existing_workflow = {"nodes": [], "edges": []}
        workflow_analysis = {
            "inputs": [{"name": "Age", "type": "int", "id": "input_age"}]
        }
        
        args = {
            "operations": [
                {
                    "op": "add_node",
                    "type": "decision",
                    "label": "Height > 180",  # Height is not registered
                    "id": "temp_1",
                    "x": 0,
                    "y": 0
                }
            ]
        }
        session_state = {
            "current_workflow": existing_workflow,
            "workflow_analysis": workflow_analysis
        }

        result = self.tool.execute(args, session_state=session_state)
        
        assert result["success"] is False
        assert "VALIDATION_FAILED" in result.get("error_code", "")
        assert "Height" in result.get("error", "")

    def test_batch_modify_decision_with_invalid_input(self):
        """Should reject batch modification referencing unregistered input"""
        existing_workflow = {
            "nodes": [
                {"id": "d1", "type": "decision", "label": "Age > 10", "x": 0, "y": 0, "color": "amber"},
                {"id": "y", "type": "end", "label": "Yes", "x": 100, "y": 0, "color": "green"},
                {"id": "n", "type": "end", "label": "No", "x": 100, "y": 100, "color": "green"},
            ],
            "edges": [
                {"from": "d1", "to": "y", "label": "true"},
                {"from": "d1", "to": "n", "label": "false"},
            ]
        }
        workflow_analysis = {
            "inputs": [{"name": "Age", "type": "int", "id": "input_age"}]
        }
        
        args = {
            "operations": [
                {
                    "op": "modify_node",
                    "node_id": "d1",
                    "label": "Height > 180"  # Height is not registered
                }
            ]
        }
        session_state = {
            "current_workflow": existing_workflow,
            "workflow_analysis": workflow_analysis
        }

        result = self.tool.execute(args, session_state=session_state)
        
        assert result["success"] is False
        assert "VALIDATION_FAILED" in result.get("error_code", "")
        assert "Height" in result.get("error", "")
