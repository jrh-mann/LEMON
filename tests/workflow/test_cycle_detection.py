"""Tests for cycle detection in workflow validator."""

import pytest
from src.backend.validation.workflow_validator import (
    WorkflowValidator,
    ValidationError,
)


class TestCycleDetection:
    """Test cycle and self-loop detection in workflows."""

    def setup_method(self):
        """Setup validator instance for each test"""
        self.validator = WorkflowValidator()

    def test_self_loop_is_rejected(self):
        """A node with an edge to itself should be rejected."""
        workflow = {
            "nodes": [
                {"id": "node_1", "type": "process", "label": "A", "x": 0, "y": 0},
            ],
            "edges": [
                {"id": "self_loop", "from": "node_1", "to": "node_1", "label": ""}
            ],
        }
        is_valid, errors = self.validator.validate(workflow)
        assert not is_valid
        assert any(err.code == "SELF_LOOP_DETECTED" for err in errors)
        # Should identify the specific node
        self_loop_error = next(err for err in errors if err.code == "SELF_LOOP_DETECTED")
        assert self_loop_error.node_id == "node_1"

    def test_simple_two_node_cycle_is_rejected(self):
        """A simple cycle between two nodes should be rejected."""
        workflow = {
            "nodes": [
                {"id": "node_1", "type": "process", "label": "A", "x": 0, "y": 0},
                {"id": "node_2", "type": "process", "label": "B", "x": 100, "y": 0},
            ],
            "edges": [
                {"id": "1->2", "from": "node_1", "to": "node_2", "label": ""},
                {"id": "2->1", "from": "node_2", "to": "node_1", "label": ""},
            ],
        }
        is_valid, errors = self.validator.validate(workflow, strict=False)
        assert not is_valid
        assert any(err.code == "CYCLE_DETECTED" for err in errors)

    def test_three_node_cycle_is_rejected(self):
        """A cycle involving three nodes should be rejected."""
        workflow = {
            "nodes": [
                {"id": "node_1", "type": "process", "label": "A", "x": 0, "y": 0},
                {"id": "node_2", "type": "process", "label": "B", "x": 100, "y": 0},
                {"id": "node_3", "type": "process", "label": "C", "x": 200, "y": 0},
            ],
            "edges": [
                {"id": "1->2", "from": "node_1", "to": "node_2", "label": ""},
                {"id": "2->3", "from": "node_2", "to": "node_3", "label": ""},
                {"id": "3->1", "from": "node_3", "to": "node_1", "label": ""},
            ],
        }
        is_valid, errors = self.validator.validate(workflow, strict=False)
        assert not is_valid
        assert any(err.code == "CYCLE_DETECTED" for err in errors)

    def test_complex_cycle_is_rejected(self):
        """A complex workflow with a cycle should be rejected."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "n1", "type": "process", "label": "A", "x": 100, "y": 0},
                {"id": "n2", "type": "process", "label": "B", "x": 200, "y": 0},
                {"id": "n3", "type": "process", "label": "C", "x": 300, "y": 0},
                {"id": "end", "type": "end", "label": "End", "x": 400, "y": 0},
            ],
            "edges": [
                {"id": "start->n1", "from": "start", "to": "n1", "label": ""},
                {"id": "n1->n2", "from": "n1", "to": "n2", "label": ""},
                {"id": "n2->n3", "from": "n2", "to": "n3", "label": ""},
                {"id": "n3->n1", "from": "n3", "to": "n1", "label": ""},  # Cycle!
                {"id": "n3->end", "from": "n3", "to": "end", "label": ""},
            ],
        }
        is_valid, errors = self.validator.validate(workflow, strict=False)
        assert not is_valid
        assert any(err.code == "CYCLE_DETECTED" for err in errors)

    def test_decision_node_cycle_is_rejected(self):
        """A cycle involving a decision node should be rejected."""
        workflow = {
            "nodes": [
                {"id": "decision", "type": "decision", "label": "Check?", "x": 0, "y": 0},
                {"id": "process", "type": "process", "label": "Process", "x": 100, "y": 0},
            ],
            "edges": [
                {"id": "d->p", "from": "decision", "to": "process", "label": "true"},
                {"id": "p->d", "from": "process", "to": "decision", "label": ""},
            ],
        }
        is_valid, errors = self.validator.validate(workflow, strict=False)
        assert not is_valid
        assert any(err.code == "CYCLE_DETECTED" for err in errors)

    def test_valid_dag_is_accepted(self):
        """A valid directed acyclic graph should be accepted."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "n1", "type": "process", "label": "A", "x": 100, "y": 0},
                {"id": "n2", "type": "process", "label": "B", "x": 200, "y": 50},
                {"id": "n3", "type": "process", "label": "C", "x": 200, "y": -50},
                {"id": "end", "type": "end", "label": "End", "x": 300, "y": 0},
            ],
            "edges": [
                {"id": "start->n1", "from": "start", "to": "n1", "label": ""},
                {"id": "n1->n2", "from": "n1", "to": "n2", "label": ""},
                {"id": "n1->n3", "from": "n1", "to": "n3", "label": ""},
                {"id": "n2->end", "from": "n2", "to": "end", "label": ""},
                {"id": "n3->end", "from": "n3", "to": "end", "label": ""},
            ],
        }
        is_valid, errors = self.validator.validate(workflow, strict=False)
        # Should pass in non-strict mode (ignoring decision branch rules)
        assert is_valid or not any(err.code in ["CYCLE_DETECTED", "SELF_LOOP_DETECTED"] for err in errors)

    def test_multiple_disconnected_components_no_cycles(self):
        """Multiple disconnected DAGs should be valid."""
        workflow = {
            "nodes": [
                {"id": "n1", "type": "start", "label": "A1", "x": 0, "y": 0},
                {"id": "n2", "type": "end", "label": "A2", "x": 100, "y": 0},
                {"id": "n3", "type": "start", "label": "B1", "x": 0, "y": 200},
                {"id": "n4", "type": "end", "label": "B2", "x": 100, "y": 200},
            ],
            "edges": [
                {"id": "n1->n2", "from": "n1", "to": "n2", "label": ""},
                {"id": "n3->n4", "from": "n3", "to": "n4", "label": ""},
            ],
        }
        is_valid, errors = self.validator.validate(workflow, strict=False)
        assert is_valid or not any(err.code in ["CYCLE_DETECTED", "SELF_LOOP_DETECTED"] for err in errors)

    def test_cycle_error_message_is_informative(self):
        """Cycle error messages should be helpful."""
        workflow = {
            "nodes": [
                {"id": "node_1", "type": "process", "label": "Step A", "x": 0, "y": 0},
                {"id": "node_2", "type": "process", "label": "Step B", "x": 100, "y": 0},
            ],
            "edges": [
                {"id": "1->2", "from": "node_1", "to": "node_2", "label": ""},
                {"id": "2->1", "from": "node_2", "to": "node_1", "label": ""},
            ],
        }
        is_valid, errors = self.validator.validate(workflow, strict=False)
        assert not is_valid

        cycle_errors = [err for err in errors if err.code == "CYCLE_DETECTED"]
        assert len(cycle_errors) > 0

        # Error message should mention the cycle
        error_msg = cycle_errors[0].message
        assert "cycle" in error_msg.lower()

    def test_empty_workflow_has_no_cycles(self):
        """Empty workflow should not have cycles."""
        workflow = {"nodes": [], "edges": []}
        is_valid, errors = self.validator.validate(workflow)
        assert is_valid
        assert not any(err.code in ["CYCLE_DETECTED", "SELF_LOOP_DETECTED"] for err in errors)

    def test_single_node_no_cycles(self):
        """Single node with no edges should not have cycles."""
        workflow = {
            "nodes": [
                {"id": "node_1", "type": "start", "label": "Alone", "x": 0, "y": 0},
            ],
            "edges": [],
        }
        is_valid, errors = self.validator.validate(workflow)
        assert is_valid
        assert not any(err.code in ["CYCLE_DETECTED", "SELF_LOOP_DETECTED"] for err in errors)

    def test_diamond_pattern_no_cycle(self):
        """Diamond pattern (convergent paths) should be valid - not a cycle."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "left", "type": "process", "label": "Left", "x": 100, "y": -50},
                {"id": "right", "type": "process", "label": "Right", "x": 100, "y": 50},
                {"id": "end", "type": "end", "label": "End", "x": 200, "y": 0},
            ],
            "edges": [
                {"id": "start->left", "from": "start", "to": "left", "label": ""},
                {"id": "start->right", "from": "start", "to": "right", "label": ""},
                {"id": "left->end", "from": "left", "to": "end", "label": ""},
                {"id": "right->end", "from": "right", "to": "end", "label": ""},
            ],
        }
        is_valid, errors = self.validator.validate(workflow, strict=False)
        assert is_valid or not any(err.code in ["CYCLE_DETECTED", "SELF_LOOP_DETECTED"] for err in errors)

    def test_self_loop_on_decision_node(self):
        """Decision node with self-loop should be rejected."""
        workflow = {
            "nodes": [
                {"id": "decision", "type": "decision", "label": "Retry?", "x": 0, "y": 0},
            ],
            "edges": [
                {"id": "retry", "from": "decision", "to": "decision", "label": "true"}
            ],
        }
        is_valid, errors = self.validator.validate(workflow, strict=False)
        assert not is_valid
        assert any(err.code == "SELF_LOOP_DETECTED" for err in errors)
