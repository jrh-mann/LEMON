"""Tests for GetCurrentWorkflowTool variables display"""

import pytest
from src.backend.tools.workflow_edit.get_current import GetCurrentWorkflowTool

class TestGetCurrentWorkflowVariables:
    """Test that variables are included in workflow and summary"""

    def setup_method(self):
        self.tool = GetCurrentWorkflowTool()

    def test_includes_registered_variables(self):
        """Should include registered variables in output"""
        workflow = {
            "nodes": [],
            "edges": []
        }
        variables = [
            {"name": "Age", "type": "int", "id": "input_age"},
            {"name": "Smoker", "type": "bool", "id": "input_smoker"}
        ]
        session_state = {
            "current_workflow": workflow,
            "workflow_analysis": {"variables": variables}
        }
        result = self.tool.execute({}, session_state=session_state)

        assert result["success"] is True
        
        # Check workflow dict has variables
        assert "variables" in result["workflow"]
        assert len(result["workflow"]["variables"]) == 2
        assert result["workflow"]["variables"][0]["name"] == "Age"
        
        # Check summary has variable descriptions
        summary = result["summary"]
        assert "variable_descriptions" in summary
        assert "Age" in summary["variable_descriptions"]
        assert "Smoker" in summary["variable_descriptions"]
        # Backwards compat alias should also work
        assert "input_descriptions" in summary

    def test_handles_no_variables(self):
        """Should handle missing variables gracefully"""
        workflow = {"nodes": [], "edges": []}
        session_state = {
            "current_workflow": workflow,
            # No workflow_analysis or variables
        }
        result = self.tool.execute({}, session_state=session_state)

        assert result["success"] is True
        # Should not crash, variables optional in workflow dict
        assert "variables" not in result["workflow"]
        
        summary = result["summary"]
        assert "No variables" in summary["variable_descriptions"]
