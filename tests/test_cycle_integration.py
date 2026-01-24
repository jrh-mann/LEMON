"""Integration test for cycle detection with workflow tools."""

import pytest
from src.backend.tools.workflow_edit import AddNodeTool, AddConnectionTool
from src.backend.validation.workflow_validator import WorkflowValidator


class TestCycleIntegration:
    """Test that tools properly reject workflows with cycles."""

    def setup_method(self):
        """Setup tools and validator for each test"""
        self.add_node_tool = AddNodeTool()
        self.add_connection_tool = AddConnectionTool()
        self.validator = WorkflowValidator()

    def test_tools_reject_self_loop_creation(self):
        """AddConnectionTool should reject creating a self-loop."""
        # Create a workflow with one node
        workflow = {
            "nodes": [
                {"id": "node_1", "type": "process", "label": "Process", "x": 100, "y": 100}
            ],
            "edges": []
        }

        session_state = {"current_workflow": workflow}

        # Try to add a self-loop
        result = self.add_connection_tool.execute(
            {"from_node_id": "node_1", "to_node_id": "node_1"},
            session_state=session_state
        )

        # Should fail validation
        assert not result["success"]
        assert "self-loop" in result["error"].lower() or "cycle" in result["error"].lower()

    def test_tools_reject_simple_cycle_creation(self):
        """AddConnectionTool should reject creating a simple cycle."""
        # Create a workflow with two connected nodes
        workflow = {
            "nodes": [
                {"id": "node_1", "type": "process", "label": "A", "x": 100, "y": 100},
                {"id": "node_2", "type": "process", "label": "B", "x": 200, "y": 100}
            ],
            "edges": [
                {"id": "edge_1", "from": "node_1", "to": "node_2", "label": ""}
            ]
        }

        session_state = {"current_workflow": workflow}

        # Try to add the back edge that would create a cycle
        result = self.add_connection_tool.execute(
            {"from_node_id": "node_2", "to_node_id": "node_1"},
            session_state=session_state
        )

        # Should fail validation
        assert not result["success"]
        assert "cycle" in result["error"].lower()

    def test_tools_accept_valid_dag(self):
        """AddConnectionTool should accept creating valid DAG structures."""
        # Create a diamond pattern (not a cycle)
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 100, "y": 0},
                {"id": "left", "type": "process", "label": "Left", "x": 0, "y": 100},
                {"id": "right", "type": "process", "label": "Right", "x": 200, "y": 100},
                {"id": "end", "type": "end", "label": "End", "x": 100, "y": 200}
            ],
            "edges": [
                {"id": "start->left", "from": "start", "to": "left", "label": ""},
                {"id": "start->right", "from": "start", "to": "right", "label": ""},
                {"id": "left->end", "from": "left", "to": "end", "label": ""}
            ]
        }

        session_state = {"current_workflow": workflow}

        # Add the final edge to complete the diamond
        result = self.add_connection_tool.execute(
            {"from_node_id": "right", "to_node_id": "end"},
            session_state=session_state
        )

        # Should succeed - diamond is not a cycle
        assert result["success"]

    def test_tools_reject_complex_cycle(self):
        """AddConnectionTool should reject creating complex multi-node cycles."""
        # Create a longer chain
        workflow = {
            "nodes": [
                {"id": "n1", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "n2", "type": "process", "label": "A", "x": 100, "y": 0},
                {"id": "n3", "type": "process", "label": "B", "x": 200, "y": 0},
                {"id": "n4", "type": "process", "label": "C", "x": 300, "y": 0},
                {"id": "n5", "type": "end", "label": "End", "x": 400, "y": 0}
            ],
            "edges": [
                {"id": "n1->n2", "from": "n1", "to": "n2", "label": ""},
                {"id": "n2->n3", "from": "n2", "to": "n3", "label": ""},
                {"id": "n3->n4", "from": "n3", "to": "n4", "label": ""},
                {"id": "n4->n5", "from": "n4", "to": "n5", "label": ""}
            ]
        }

        session_state = {"current_workflow": workflow}

        # Try to add an edge that creates a cycle (n4 back to n2)
        result = self.add_connection_tool.execute(
            {"from_node_id": "n4", "to_node_id": "n2"},
            session_state=session_state
        )

        # Should fail validation
        assert not result["success"]
        assert "cycle" in result["error"].lower()

    def test_validator_detects_existing_cycle(self):
        """Validator should detect cycles in existing workflows."""
        # Workflow with pre-existing cycle
        workflow = {
            "nodes": [
                {"id": "n1", "type": "process", "label": "A", "x": 0, "y": 0},
                {"id": "n2", "type": "process", "label": "B", "x": 100, "y": 0},
                {"id": "n3", "type": "process", "label": "C", "x": 200, "y": 0}
            ],
            "edges": [
                {"id": "n1->n2", "from": "n1", "to": "n2", "label": ""},
                {"id": "n2->n3", "from": "n2", "to": "n3", "label": ""},
                {"id": "n3->n1", "from": "n3", "to": "n1", "label": ""}  # Cycle!
            ]
        }

        is_valid, errors = self.validator.validate(workflow, strict=False)

        assert not is_valid
        assert any(err.code == "CYCLE_DETECTED" for err in errors)

        # Check that error message includes the cycle path
        cycle_error = next(err for err in errors if err.code == "CYCLE_DETECTED")
        assert "→" in cycle_error.message  # Should show cycle path with arrows
