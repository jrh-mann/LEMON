"""Tests for ModifyNodeTool validation logic.

All workflow tools now require workflow_id parameter - workflows must be created first
using create_workflow, then tools operate on them by ID with auto-save to database.
"""

import pytest
from src.backend.tools.workflow_edit.modify_node import ModifyNodeTool
from tests.conftest import make_session_with_workflow


class TestModifyNodeValidation:
    """Test validation in ModifyNodeTool"""

    def setup_method(self):
        self.tool = ModifyNodeTool()

    def test_modify_decision_label_with_valid_input(self, workflow_store, test_user_id):
        """Should accept modification when condition references registered variable"""
        nodes = [
            {
                "id": "d1", 
                "type": "decision", 
                "label": "Old Label", 
                "x": 0, 
                "y": 0, 
                "color": "amber",
                "condition": {"input_id": "input_age", "comparator": "gt", "value": 10}
            },
            {"id": "y", "type": "end", "label": "Yes", "x": 100, "y": 0, "color": "green"},
            {"id": "n", "type": "end", "label": "No", "x": 100, "y": 100, "color": "green"},
        ]
        edges = [
            {"from": "d1", "to": "y", "label": "true"},
            {"from": "d1", "to": "n", "label": "false"},
        ]
        variables = [{"name": "Age", "type": "int", "id": "input_age", "source": "input"}]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, edges=edges, variables=variables
        )
        session["workflow_analysis"] = {"variables": variables}
        
        # Just changing the label, keeping existing valid condition
        args = {"workflow_id": workflow_id, "node_id": "d1", "label": "Age Check"}

        result = self.tool.execute(args, session_state=session)
        
        assert result["success"] is True
        assert result["node"]["label"] == "Age Check"

    def test_modify_decision_label_with_invalid_input(self, workflow_store, test_user_id):
        """Should reject modification when new condition references unregistered variable"""
        nodes = [
            {
                "id": "d1", 
                "type": "decision", 
                "label": "Age Check", 
                "x": 0, 
                "y": 0, 
                "color": "amber",
                "condition": {"input_id": "input_age", "comparator": "gt", "value": 10}
            },
            {"id": "y", "type": "end", "label": "Yes", "x": 100, "y": 0, "color": "green"},
            {"id": "n", "type": "end", "label": "No", "x": 100, "y": 100, "color": "green"},
        ]
        edges = [
            {"from": "d1", "to": "y", "label": "true"},
            {"from": "d1", "to": "n", "label": "false"},
        ]
        variables = [{"name": "Age", "type": "int", "id": "input_age", "source": "input"}]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, edges=edges, variables=variables
        )
        session["workflow_analysis"] = {"variables": variables}
        
        # Try to change condition to reference "Height" which doesn't exist
        args = {
            "workflow_id": workflow_id,
            "node_id": "d1", 
            "label": "Height Check",
            "condition": {"input_id": "input_height", "comparator": "gt", "value": 180}
        }

        result = self.tool.execute(args, session_state=session)
        
        assert result["success"] is False
        assert "INVALID_CONDITION" in result.get("error_code", "") or "VALIDATION_FAILED" in result.get("error_code", "")
        assert "input_height" in result.get("error", "") or "not found" in result.get("error", "").lower()

    def test_modify_decision_with_invalid_condition_input_fails(self, workflow_store, test_user_id):
        """Modifying a decision node with invalid condition input_id should fail."""
        nodes = [
            {
                "id": "d1", 
                "type": "decision", 
                "label": "Age > 10", 
                "x": 0, 
                "y": 0, 
                "color": "amber",
                "condition": {
                    "input_id": "input_age_int",
                    "comparator": "gt",
                    "value": 10
                }
            },
            {"id": "y", "type": "end", "label": "Yes", "x": 100, "y": 0, "color": "green"},
            {"id": "n", "type": "end", "label": "No", "x": 100, "y": 100, "color": "green"},
        ]
        edges = [
            {"from": "d1", "to": "y", "label": "true"},
            {"from": "d1", "to": "n", "label": "false"},
        ]
        variables = [{"name": "Age", "type": "int", "id": "input_age_int", "source": "input"}]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, edges=edges, variables=variables
        )
        session["workflow_analysis"] = {"variables": variables}
        
        # Try to modify with condition referencing non-existent input
        args = {
            "workflow_id": workflow_id,
            "node_id": "d1", 
            "label": "BMI > 18",
            "condition": {
                "input_id": "input_bmi_float",  # This doesn't exist!
                "comparator": "gt",
                "value": 18
            }
        }

        result = self.tool.execute(args, session_state=session)
        
        assert result["success"] is False
        assert "input_bmi_float" in result.get("error", "") or "not found" in result.get("error", "").lower()
