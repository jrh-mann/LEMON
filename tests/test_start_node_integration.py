"""Integration tests for start node validation with workflow tools.

All workflow tools now require workflow_id parameter - workflows must be created first
using create_workflow, then tools operate on them by ID with auto-save to database.
"""

import pytest
from src.backend.tools.workflow_edit import AddNodeTool, ModifyNodeTool, BatchEditWorkflowTool
from src.backend.validation.workflow_validator import WorkflowValidator
from tests.conftest import make_session_with_workflow


class TestStartNodeIntegration:
    """Test that tools properly enforce single start node rule."""

    def setup_method(self):
        """Setup tools and validator for each test"""
        self.add_node_tool = AddNodeTool()
        self.modify_node_tool = ModifyNodeTool()
        self.batch_tool = BatchEditWorkflowTool()
        self.validator = WorkflowValidator()

    def test_add_second_start_node_rejected(self, workflow_store, test_user_id):
        """AddNodeTool should reject adding a second start node."""
        # Workflow with one start node
        nodes = [
            {"id": "start1", "type": "start", "label": "Start 1", "x": 100, "y": 100}
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes
        )

        # Try to add a second start node
        result = self.add_node_tool.execute(
            {
                "workflow_id": workflow_id,
                "type": "start",
                "label": "Start 2",
                "x": 200,
                "y": 100
            },
            session_state=session
        )

        # Should fail validation
        assert not result["success"]
        assert "multiple" in result["error"].lower() or "exactly one" in result["error"].lower()

    def test_add_first_start_node_succeeds(self, workflow_store, test_user_id):
        """AddNodeTool should allow adding the first start node."""
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id
        )

        # Add the first start node
        result = self.add_node_tool.execute(
            {
                "workflow_id": workflow_id,
                "type": "start",
                "label": "Start",
                "x": 100,
                "y": 100
            },
            session_state=session
        )

        # Should succeed
        assert result["success"]

    def test_modify_node_to_start_when_start_exists_rejected(self, workflow_store, test_user_id):
        """ModifyNodeTool should reject changing a node to 'start' when one exists."""
        nodes = [
            {"id": "start", "type": "start", "label": "Start", "x": 100, "y": 100},
            {"id": "proc", "type": "process", "label": "Process", "x": 200, "y": 100},
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes
        )

        # Try to change process node to start
        result = self.modify_node_tool.execute(
            {
                "workflow_id": workflow_id,
                "node_id": "proc",
                "type": "start"
            },
            session_state=session
        )

        # Should fail validation
        assert not result["success"]
        assert "multiple" in result["error"].lower() or "start" in result["error"].lower()

    def test_modify_node_to_start_when_no_start_exists_succeeds(self, workflow_store, test_user_id):
        """ModifyNodeTool should allow changing node to 'start' when none exists."""
        nodes = [
            {"id": "proc", "type": "process", "label": "Process", "x": 100, "y": 100},
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes
        )

        # Change process node to start
        result = self.modify_node_tool.execute(
            {
                "workflow_id": workflow_id,
                "node_id": "proc",
                "type": "start"
            },
            session_state=session
        )

        # Should succeed
        assert result["success"]

    def test_modify_start_node_type_to_process_succeeds(self, workflow_store, test_user_id):
        """ModifyNodeTool should allow changing start node to another type."""
        nodes = [
            {"id": "start", "type": "start", "label": "Start", "x": 100, "y": 100},
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes
        )

        # Change start to process
        result = self.modify_node_tool.execute(
            {
                "workflow_id": workflow_id,
                "node_id": "start",
                "type": "process"
            },
            session_state=session
        )

        # Should succeed (now there are 0 start nodes, valid in lenient mode)
        assert result["success"]

    def test_batch_edit_creating_two_starts_rejected(self, workflow_store, test_user_id):
        """BatchEditWorkflowTool should reject batch creating multiple start nodes."""
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id
        )

        # Try to add two start nodes in one batch
        result = self.batch_tool.execute(
            {
                "workflow_id": workflow_id,
                "operations": [
                    {"op": "add_node", "type": "start", "label": "Start 1", "id": "temp_1"},
                    {"op": "add_node", "type": "start", "label": "Start 2", "id": "temp_2"},
                ]
            },
            session_state=session
        )

        # Should fail validation
        assert not result["success"]
        assert "multiple" in result["error"].lower() or "start" in result["error"].lower()

    def test_batch_edit_creating_one_start_succeeds(self, workflow_store, test_user_id):
        """BatchEditWorkflowTool should allow creating one start node."""
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id
        )

        # Add one start node
        result = self.batch_tool.execute(
            {
                "workflow_id": workflow_id,
                "operations": [
                    {"op": "add_node", "type": "start", "label": "Start", "id": "temp_1"},
                    {"op": "add_node", "type": "end", "label": "End", "id": "temp_2"},
                    {"op": "add_connection", "from": "temp_1", "to": "temp_2"},
                ]
            },
            session_state=session
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

    def test_error_propagates_to_tool_result(self, workflow_store, test_user_id):
        """Error messages should propagate correctly from validator to tool."""
        nodes = [
            {"id": "existing_start", "type": "start", "label": "Existing", "x": 0, "y": 0}
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes
        )

        # Try to add second start
        result = self.add_node_tool.execute(
            {
                "workflow_id": workflow_id,
                "type": "start",
                "label": "New Start",
                "x": 100,
                "y": 0
            },
            session_state=session
        )

        # Should have error field with validation message
        assert not result["success"]
        assert "error" in result
        assert "Existing" in result["error"]  # Should mention the existing start node
        assert "New Start" in result["error"]  # Should mention the new start node
