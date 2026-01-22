"""Tests for ModifyNodeTool validation logic"""

import pytest
from src.backend.tools.workflow_edit.modify_node import ModifyNodeTool

class TestModifyNodeValidation:
    """Test validation in ModifyNodeTool"""

    def setup_method(self):
        self.tool = ModifyNodeTool()

    def test_modify_decision_label_with_valid_input(self):
        """Should accept modification referencing registered input"""
        existing_workflow = {
            "nodes": [
                {"id": "d1", "type": "decision", "label": "Old > 10", "x": 0, "y": 0, "color": "amber"},
                {"id": "y", "type": "end", "label": "Yes", "x": 100, "y": 0, "color": "green"},
                {"id": "n", "type": "end", "label": "No", "x": 100, "y": 100, "color": "green"},
            ],
            "edges": [
                {"from": "d1", "to": "y", "label": "true"},
                {"from": "d1", "to": "n", "label": "false"},
            ]
        }
        # Registered inputs: Age
        workflow_analysis = {
            "inputs": [{"name": "Age", "type": "int", "id": "input_age"}]
        }
        
        args = {"node_id": "d1", "label": "Age > 18"}
        session_state = {
            "current_workflow": existing_workflow,
            "workflow_analysis": workflow_analysis
        }

        result = self.tool.execute(args, session_state=session_state)
        
        assert result["success"] is True
        assert result["node"]["label"] == "Age > 18"

    def test_modify_decision_label_with_invalid_input(self):
        """Should reject modification referencing unregistered input"""
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
        # Registered inputs: Age
        workflow_analysis = {
            "inputs": [{"name": "Age", "type": "int", "id": "input_age"}]
        }
        
        # Try to reference "Height"
        args = {"node_id": "d1", "label": "Height > 180"}
        session_state = {
            "current_workflow": existing_workflow,
            "workflow_analysis": workflow_analysis
        }

        result = self.tool.execute(args, session_state=session_state)
        
        assert result["success"] is False
        assert "VALIDATION_FAILED" in result.get("error_code", "")
        assert "Height" in result.get("error", "")

    def test_modify_decision_label_syntax_error(self):
        """Should reject modification with invalid syntax"""
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
        
        args = {"node_id": "d1", "label": "Age >> 18"}
        session_state = {
            "current_workflow": existing_workflow,
            "workflow_analysis": workflow_analysis
        }

        result = self.tool.execute(args, session_state=session_state)
        
        assert result["success"] is False
        assert "VALIDATION_FAILED" in result.get("error_code", "")
        assert "syntax" in result.get("error", "").lower()
