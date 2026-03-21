"""Tests for start node validation rules."""

import pytest
from src.backend.validation.workflow_validator import (
    WorkflowValidator,
    ValidationError,
)


class TestStartNodeValidation:
    """Test start node count validation in workflows."""

    def setup_method(self):
        """Setup validator instance for each test"""
        self.validator = WorkflowValidator()

    def test_empty_workflow_is_valid(self):
        """Empty workflow (0 nodes, 0 start nodes) should be valid."""
        workflow = {"nodes": [], "edges": []}
        is_valid, errors = self.validator.validate(workflow, strict=True)
        assert is_valid
        assert not any(err.code in ["MULTIPLE_START_NODES", "NO_START_NODE"] for err in errors)

    def test_single_start_node_is_valid(self):
        """Workflow with exactly one start node should be valid."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Begin", "x": 0, "y": 0},
                {"id": "end", "type": "end", "label": "End", "x": 100, "y": 0},
            ],
            "edges": [
                {"id": "start->end", "from": "start", "to": "end", "label": ""}
            ],
        }
        is_valid, errors = self.validator.validate(workflow, strict=True)
        assert is_valid
        assert not any(err.code in ["MULTIPLE_START_NODES", "NO_START_NODE"] for err in errors)

    def test_two_start_nodes_rejected_in_strict_mode(self):
        """Two start nodes should be rejected (strict mode)."""
        workflow = {
            "nodes": [
                {"id": "start1", "type": "start", "label": "Start 1", "x": 0, "y": 0},
                {"id": "start2", "type": "start", "label": "Start 2", "x": 0, "y": 100},
                {"id": "end", "type": "end", "label": "End", "x": 200, "y": 50},
            ],
            "edges": [
                {"id": "start1->end", "from": "start1", "to": "end", "label": ""},
                {"id": "start2->end", "from": "start2", "to": "end", "label": ""},
            ],
        }
        is_valid, errors = self.validator.validate(workflow, strict=True)
        assert not is_valid
        assert any(err.code == "MULTIPLE_START_NODES" for err in errors)

    def test_two_start_nodes_rejected_in_lenient_mode(self):
        """Two start nodes should be rejected even in lenient mode (always enforced)."""
        workflow = {
            "nodes": [
                {"id": "start1", "type": "start", "label": "Start 1", "x": 0, "y": 0},
                {"id": "start2", "type": "start", "label": "Start 2", "x": 0, "y": 100},
            ],
            "edges": [],
        }
        is_valid, errors = self.validator.validate(workflow, strict=False)
        assert not is_valid
        assert any(err.code == "MULTIPLE_START_NODES" for err in errors)

    def test_three_start_nodes_rejected(self):
        """Three or more start nodes should be rejected."""
        workflow = {
            "nodes": [
                {"id": "start1", "type": "start", "label": "Start 1", "x": 0, "y": 0},
                {"id": "start2", "type": "start", "label": "Start 2", "x": 0, "y": 100},
                {"id": "start3", "type": "start", "label": "Start 3", "x": 0, "y": 200},
                {"id": "end", "type": "end", "label": "End", "x": 200, "y": 100},
            ],
            "edges": [],
        }
        is_valid, errors = self.validator.validate(workflow, strict=False)
        assert not is_valid

        multiple_start_errors = [err for err in errors if err.code == "MULTIPLE_START_NODES"]
        assert len(multiple_start_errors) > 0

        # Should mention the count
        error_msg = multiple_start_errors[0].message
        assert "3" in error_msg or "three" in error_msg.lower()

    def test_error_message_lists_all_start_nodes(self):
        """Error message should list all start node labels."""
        workflow = {
            "nodes": [
                {"id": "s1", "type": "start", "label": "Entry Point A", "x": 0, "y": 0},
                {"id": "s2", "type": "start", "label": "Entry Point B", "x": 0, "y": 100},
            ],
            "edges": [],
        }
        is_valid, errors = self.validator.validate(workflow, strict=False)
        assert not is_valid

        multiple_start_error = next(err for err in errors if err.code == "MULTIPLE_START_NODES")
        error_msg = multiple_start_error.message

        # Should mention both labels
        assert "Entry Point A" in error_msg
        assert "Entry Point B" in error_msg

    def test_zero_start_nodes_valid_in_lenient_mode(self):
        """Zero start nodes should be valid in lenient mode (allows incremental construction)."""
        workflow = {
            "nodes": [
                {"id": "proc", "type": "process", "label": "Process", "x": 100, "y": 100},
                {"id": "end", "type": "end", "label": "End", "x": 200, "y": 100},
            ],
            "edges": [
                {"id": "proc->end", "from": "proc", "to": "end", "label": ""}
            ],
        }
        is_valid, errors = self.validator.validate(workflow, strict=False)
        # Should pass in lenient mode (no start node error)
        assert is_valid or not any(err.code == "NO_START_NODE" for err in errors)

    def test_zero_start_nodes_invalid_in_strict_mode(self):
        """Zero start nodes should be invalid in strict mode when other nodes exist."""
        workflow = {
            "nodes": [
                {"id": "proc", "type": "process", "label": "Process", "x": 100, "y": 100},
                {"id": "end", "type": "end", "label": "End", "x": 200, "y": 100},
            ],
            "edges": [
                {"id": "proc->end", "from": "proc", "to": "end", "label": ""}
            ],
        }
        is_valid, errors = self.validator.validate(workflow, strict=True)
        assert not is_valid
        assert any(err.code == "NO_START_NODE" for err in errors)

    def test_zero_start_nodes_empty_workflow_valid_strict(self):
        """Empty workflow should be valid even in strict mode (nothing to validate)."""
        workflow = {"nodes": [], "edges": []}
        is_valid, errors = self.validator.validate(workflow, strict=True)
        assert is_valid

    def test_disconnected_components_with_multiple_starts_rejected(self):
        """Multiple disconnected DAGs each with start node should be rejected."""
        workflow = {
            "nodes": [
                # Component 1
                {"id": "start1", "type": "start", "label": "Start 1", "x": 0, "y": 0},
                {"id": "end1", "type": "end", "label": "End 1", "x": 100, "y": 0},
                # Component 2
                {"id": "start2", "type": "start", "label": "Start 2", "x": 0, "y": 200},
                {"id": "end2", "type": "end", "label": "End 2", "x": 100, "y": 200},
            ],
            "edges": [
                {"id": "start1->end1", "from": "start1", "to": "end1", "label": ""},
                {"id": "start2->end2", "from": "start2", "to": "end2", "label": ""},
            ],
        }
        is_valid, errors = self.validator.validate(workflow, strict=False)
        assert not is_valid
        assert any(err.code == "MULTIPLE_START_NODES" for err in errors)

    def test_complex_workflow_with_single_start(self):
        """Complex workflow with one start node should be valid."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 100},
                {"id": "p1", "type": "process", "label": "Process 1", "x": 100, "y": 100},
                {"id": "decision", "type": "decision", "label": "Check?", "x": 200, "y": 100},
                {"id": "p2", "type": "process", "label": "Process 2", "x": 300, "y": 50},
                {"id": "p3", "type": "process", "label": "Process 3", "x": 300, "y": 150},
                {"id": "end", "type": "end", "label": "End", "x": 400, "y": 100},
            ],
            "edges": [
                {"id": "start->p1", "from": "start", "to": "p1", "label": ""},
                {"id": "p1->decision", "from": "p1", "to": "decision", "label": ""},
                {"id": "decision->p2", "from": "decision", "to": "p2", "label": "true"},
                {"id": "decision->p3", "from": "decision", "to": "p3", "label": "false"},
                {"id": "p2->end", "from": "p2", "to": "end", "label": ""},
                {"id": "p3->end", "from": "p3", "to": "end", "label": ""},
            ],
        }
        is_valid, errors = self.validator.validate(workflow, strict=False)
        # Should not have start node errors (may have other errors in strict mode)
        assert not any(err.code in ["MULTIPLE_START_NODES", "NO_START_NODE"] for err in errors)

    def test_error_message_format(self):
        """Error message should be clear and actionable."""
        workflow = {
            "nodes": [
                {"id": "s1", "type": "start", "label": "First", "x": 0, "y": 0},
                {"id": "s2", "type": "start", "label": "Second", "x": 0, "y": 100},
            ],
            "edges": [],
        }
        is_valid, errors = self.validator.validate(workflow, strict=False)

        multiple_start_error = next(err for err in errors if err.code == "MULTIPLE_START_NODES")
        error_msg = multiple_start_error.message.lower()

        # Should explain the problem clearly
        assert "exactly one" in error_msg or "must have" in error_msg
        assert "2" in multiple_start_error.message or "two" in error_msg
