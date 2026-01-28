"""Tests for GetCurrentWorkflowTool inputs display"""

import pytest
from src.backend.tools.workflow_edit.get_current import GetCurrentWorkflowTool

class TestGetCurrentWorkflowInputs:
    """Test that inputs are included in workflow and summary"""

    def setup_method(self):
        self.tool = GetCurrentWorkflowTool()

    def test_includes_registered_inputs(self):
        """Should include registered inputs in output"""
        workflow = {
            "nodes": [],
            "edges": []
        }
        inputs = [
            {"name": "Age", "type": "int", "id": "input_age"},
            {"name": "Smoker", "type": "bool", "id": "input_smoker"}
        ]
        session_state = {
            "current_workflow": workflow,
            "workflow_analysis": {"inputs": inputs}
        }
        result = self.tool.execute({}, session_state=session_state)

        assert result["success"] is True
        
        # Check workflow dict has inputs
        assert "inputs" in result["workflow"]
        assert len(result["workflow"]["inputs"]) == 2
        assert result["workflow"]["inputs"][0]["name"] == "Age"
        
        # Check summary has input descriptions
        summary = result["summary"]
        assert "input_descriptions" in summary
        assert "Age (int)" in summary["input_descriptions"]
        assert "Smoker (bool)" in summary["input_descriptions"]

    def test_handles_no_inputs(self):
        """Should handle missing inputs gracefully"""
        workflow = {"nodes": [], "edges": []}
        session_state = {
            "current_workflow": workflow,
            # No workflow_analysis or inputs
        }
        result = self.tool.execute({}, session_state=session_state)

        assert result["success"] is True
        # Should not crash, inputs optional in workflow dict depending on implementation
        # logic: if inputs: workflow["inputs"] = inputs
        assert "inputs" not in result["workflow"]
        
        summary = result["summary"]
        assert "No variables" in summary["input_descriptions"]
