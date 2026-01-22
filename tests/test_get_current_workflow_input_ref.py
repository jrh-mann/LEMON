"""Tests for GetCurrentWorkflowTool input_ref display"""

import pytest
from src.backend.tools.workflow_edit.get_current import GetCurrentWorkflowTool

class TestGetCurrentWorkflowInputRef:
    """Test that input_ref is included in summary"""

    def setup_method(self):
        self.tool = GetCurrentWorkflowTool()

    def test_summary_includes_input_ref(self):
        """Should include input_ref in node description if present"""
        workflow = {
            "nodes": [
                {
                    "id": "n1", 
                    "type": "decision", 
                    "label": "Check Age", 
                    "x": 0, 
                    "y": 0, 
                    "input_ref": "Age"
                },
                {
                    "id": "n2", 
                    "type": "start", 
                    "label": "Start", 
                    "x": 100, 
                    "y": 0
                }
            ],
            "edges": []
        }
        session_state = {"current_workflow": workflow}
        result = self.tool.execute({}, session_state=session_state)

        assert result["success"] is True
        summary = result["summary"]["node_descriptions"]
        
        # Check that n1 has input info
        assert 'n1: "Check Age" (type: decision) (input: Age)' in summary
        
        # Check that n2 (no input_ref) doesn't have it
        assert 'n2: "Start" (type: start)' in summary
        assert 'n2: "Start" (type: start) (input:' not in summary
