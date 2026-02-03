"""Tests for GetCurrentWorkflowTool variables display.

All workflow tools now require workflow_id parameter - workflows must be created first
using create_workflow, then tools operate on them by ID with auto-save to database.
"""

import pytest
from src.backend.tools.workflow_edit.get_current import GetCurrentWorkflowTool
from tests.conftest import make_session_with_workflow


class TestGetCurrentWorkflowVariables:
    """Test that variables are included in workflow and summary"""

    def setup_method(self):
        self.tool = GetCurrentWorkflowTool()

    def test_includes_registered_variables(self, workflow_store, test_user_id):
        """Should include registered variables in output"""
        variables = [
            {"name": "Age", "type": "int", "id": "input_age", "source": "input"},
            {"name": "Smoker", "type": "bool", "id": "input_smoker", "source": "input"}
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, variables=variables
        )
        session["workflow_analysis"] = {"variables": variables}
        
        result = self.tool.execute({"workflow_id": workflow_id}, session_state=session)

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

    def test_handles_no_variables(self, workflow_store, test_user_id):
        """Should handle missing variables gracefully"""
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id
        )
        # Ensure no workflow_analysis in session
        session.pop("workflow_analysis", None)
        
        result = self.tool.execute({"workflow_id": workflow_id}, session_state=session)

        assert result["success"] is True
        # Should not crash, variables optional in workflow dict
        assert "variables" not in result["workflow"] or len(result["workflow"]["variables"]) == 0
        
        summary = result["summary"]
        assert "No variables" in summary["variable_descriptions"]
