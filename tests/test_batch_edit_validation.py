"""Tests for BatchEditWorkflowTool validation logic.

All workflow tools now require workflow_id parameter - workflows must be created first
using create_workflow, then tools operate on them by ID with auto-save to database.
"""

import pytest
from src.backend.tools.workflow_edit.batch_edit import BatchEditWorkflowTool
from tests.conftest import make_session_with_workflow


class TestBatchEditValidation:
    """Test validation in BatchEditWorkflowTool"""

    def setup_method(self):
        self.tool = BatchEditWorkflowTool()

    def test_batch_add_decision_with_invalid_input(self, workflow_store, test_user_id):
        """Should reject batch operation referencing unregistered input"""
        variables = [{"name": "Age", "type": "int", "id": "input_age", "source": "input"}]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, variables=variables
        )
        session["workflow_analysis"] = {"variables": variables}
        
        args = {
            "workflow_id": workflow_id,
            "operations": [
                {
                    "op": "add_node",
                    "type": "decision",
                    "label": "Height > 180",  # Height is not registered
                    "id": "temp_1",
                    "x": 0,
                    "y": 0,
                    "condition": {
                        "input_id": "input_height_int",  # Not registered
                        "comparator": "gt",
                        "value": 180
                    }
                }
            ]
        }

        result = self.tool.execute(args, session_state=session)
        
        assert result["success"] is False
        # Should mention the invalid input_id
        assert "input_height_int" in result.get("error", "") or "not found" in result.get("error", "")

    def test_batch_modify_decision_with_invalid_input(self, workflow_store, test_user_id):
        """Should reject batch modification referencing unregistered input"""
        nodes = [
            {"id": "d1", "type": "decision", "label": "Age > 10", "x": 0, "y": 0, "color": "amber"},
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
        
        args = {
            "workflow_id": workflow_id,
            "operations": [
                {
                    "op": "modify_node",
                    "node_id": "d1",
                    "label": "Height > 180"  # Height is not registered
                }
            ]
        }

        result = self.tool.execute(args, session_state=session)
        
        assert result["success"] is False
        assert "VALIDATION_FAILED" in result.get("error_code", "")
        assert "Height" in result.get("error", "")
