"""Integration tests for start node validation with workflow tools."""

import pytest
from src.backend.tools.workflow_edit import AddNodeTool, ModifyNodeTool
from src.backend.validation.workflow_validator import WorkflowValidator


class TestStartNodeIntegration:
    """Test that tools properly enforce single start node rule."""

    def setup_method(self):
        """Setup tools and validator for each test"""
        self.add_node_tool = AddNodeTool()
        self.modify_node_tool = ModifyNodeTool()
        self.validator = WorkflowValidator()

    def test_add_second_start_node_rejected(self):
        """AddNodeTool should reject adding a second start node."""
        # Workflow with one start node
        workflow = {
            "nodes": [
                {"id": "start1", "type": "start", "label": "Start 1", "x": 100, "y": 100}
            ],
            "edges": []
        }
        session_state = {"current_workflow": workflow}

        # Try to add a second start node
        result = self.add_node_tool.execute(
            {
                "node_id": "start2",
                "type": "start",
                "label": "Start 2",
                "x": 200,
                "y": 100
            },
            session_state=session_state
        )

        # Should fail validation
        assert not result["success"]
        assert "multiple" in result["error"].lower() or "exactly one" in result["error"].lower()

    def test_add_first_start_node_succeeds(self):
        """AddNodeTool should allow adding the first start node."""
        workflow = {"nodes": [], "edges": []}
        session_state = {"current_workflow": workflow}

        # Add the first start node
        result = self.add_node_tool.execute(
            {
                "node_id": "start",
                "type": "start",
                "label": "Start",
                "x": 100,
                "y": 100
            },
            session_state=session_state
        )

        # Should succeed
        assert result["success"]

    def test_modify_node_to_start_when_start_exists_rejected(self):
        """ModifyNodeTool should reject changing a node to 'start' when one exists."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 100, "y": 100},
                {"id": "proc", "type": "process", "label": "Process", "x": 200, "y": 100},
            ],
            "edges": []
        }
        session_state = {"current_workflow": workflow}

        # Try to change process node to start
        result = self.modify_node_tool.execute(
            {
                "node_id": "proc",
                "type": "start"
            },
            session_state=session_state
        )

        # Should fail validation
        assert not result["success"]
        assert "multiple" in result["error"].lower() or "start" in result["error"].lower()

    def test_modify_node_to_start_when_no_start_exists_succeeds(self):
        """ModifyNodeTool should allow changing node to 'start' when none exists."""
        workflow = {
            "nodes": [
                {"id": "proc", "type": "process", "label": "Process", "x": 100, "y": 100},
            ],
            "edges": []
        }
        session_state = {"current_workflow": workflow}

        # Change process node to start
        result = self.modify_node_tool.execute(
            {
                "node_id": "proc",
                "type": "start"
            },
            session_state=session_state
        )

        # Should succeed
        assert result["success"]

    def test_modify_start_node_type_to_process_succeeds(self):
        """ModifyNodeTool should allow changing start node to another type."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 100, "y": 100},
            ],
            "edges": []
        }
        session_state = {"current_workflow": workflow}

        # Change start to process
        result = self.modify_node_tool.execute(
            {
                "node_id": "start",
                "type": "process"
            },
            session_state=session_state
        )

        # Should succeed (now there are 0 start nodes, valid in lenient mode)
        assert result["success"]

    def test_batch_edit_creating_two_starts_rejected(self):
        """BatchEditWorkflowTool should reject batch creating multiple start nodes."""
        from src.backend.tools.workflow_edit import BatchEditWorkflowTool

        batch_tool = BatchEditWorkflowTool()
        workflow = {"nodes": [], "edges": []}
        session_state = {"current_workflow": workflow}

        # Try to add two start nodes in one batch
        result = batch_tool.execute(
            {
                "operations": [
                    {"op": "add_node", "type": "start", "label": "Start 1", "id": "temp_1"},
                    {"op": "add_node", "type": "start", "label": "Start 2", "id": "temp_2"},
                ]
            },
            session_state=session_state
        )

        # Should fail validation
        assert not result["success"]
        assert "multiple" in result["error"].lower() or "start" in result["error"].lower()

    def test_batch_edit_creating_one_start_succeeds(self):
        """BatchEditWorkflowTool should allow creating one start node."""
        from src.backend.tools.workflow_edit import BatchEditWorkflowTool

        batch_tool = BatchEditWorkflowTool()
        workflow = {"nodes": [], "edges": []}
        session_state = {"current_workflow": workflow}

        # Add one start node
        result = batch_tool.execute(
            {
                "operations": [
                    {"op": "add_node", "type": "start", "label": "Start", "id": "temp_1"},
                    {"op": "add_node", "type": "end", "label": "End", "id": "temp_2"},
                    {"op": "add_connection", "from": "temp_1", "to": "temp_2"},
                ]
            },
            session_state=session_state
        )

        # Should succeed
        assert result["success"]

    def test_validator_detects_existing_multiple_starts(self):
        """Validator should detect multiple starts in existing workflows."""
        workflow = {
            "nodes": [
                {"id": "s1", "type": "start", "label": "Start 1", "x": 0, "y": 0},
                {"id": "s2", "type": "start", "label": "Start 2", "x": 0, "y": 100},
                {"id": "s3", "type": "start", "label": "Start 3", "x": 0, "y": 200},
            ],
            "edges": []
        }

        is_valid, errors = self.validator.validate(workflow, strict=False)

        assert not is_valid
        assert any(err.code == "MULTIPLE_START_NODES" for err in errors)

        # Check error message lists all starts
        multiple_start_error = next(err for err in errors if err.code == "MULTIPLE_START_NODES")
        assert "Start 1" in multiple_start_error.message
        assert "Start 2" in multiple_start_error.message
        assert "Start 3" in multiple_start_error.message

    def test_error_propagates_to_tool_result(self):
        """Error messages should propagate correctly from validator to tool."""
        workflow = {
            "nodes": [
                {"id": "existing_start", "type": "start", "label": "Existing", "x": 0, "y": 0}
            ],
            "edges": []
        }
        session_state = {"current_workflow": workflow}

        # Try to add second start
        result = self.add_node_tool.execute(
            {
                "node_id": "new_start",
                "type": "start",
                "label": "New Start",
                "x": 100,
                "y": 0
            },
            session_state=session_state
        )

        # Should have error field with validation message
        assert not result["success"]
        assert "error" in result
        assert "Existing" in result["error"]  # Should mention the existing start node
        assert "New Start" in result["error"]  # Should mention the new start node
