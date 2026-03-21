"""Tests for workflow validation system"""

import pytest
from src.backend.validation.workflow_validator import (
    WorkflowValidator,
    ValidationError,
)


class TestWorkflowValidator:
    """Test workflow validation rules"""

    def setup_method(self):
        """Setup validator instance for each test"""
        self.validator = WorkflowValidator()

    def test_empty_workflow_is_valid(self):
        """Empty workflow should be valid"""
        workflow = {"nodes": [], "edges": []}
        is_valid, errors = self.validator.validate(workflow)
        assert is_valid
        assert len(errors) == 0

    def test_single_node_valid(self):
        """Single well-formed node should be valid"""
        workflow = {
            "nodes": [
                {
                    "id": "node_1",
                    "type": "start",
                    "label": "Input",
                    "x": 100,
                    "y": 100,
                }
            ],
            "edges": [],
        }
        is_valid, errors = self.validator.validate(workflow)
        assert is_valid
        assert len(errors) == 0

    def test_missing_node_fields(self):
        """Node missing required fields should fail"""
        workflow = {
            "nodes": [
                {
                    "id": "node_1",
                    "type": "start",
                    # Missing: label, x, y
                }
            ],
            "edges": [],
        }
        is_valid, errors = self.validator.validate(workflow)
        assert not is_valid
        assert len(errors) > 0
        assert any(err.code == "INCOMPLETE_NODE" for err in errors)

    def test_invalid_node_type(self):
        """Node with invalid type should fail"""
        workflow = {
            "nodes": [
                {
                    "id": "node_1",
                    "type": "invalid_type",
                    "label": "Test",
                    "x": 0,
                    "y": 0,
                }
            ],
            "edges": [],
        }
        is_valid, errors = self.validator.validate(workflow)
        assert not is_valid
        assert any(err.code == "INVALID_NODE_TYPE" for err in errors)

    def test_duplicate_node_ids(self):
        """Duplicate node IDs should fail"""
        workflow = {
            "nodes": [
                {"id": "node_1", "type": "start", "label": "A", "x": 0, "y": 0},
                {"id": "node_1", "type": "end", "label": "B", "x": 100, "y": 100},
            ],
            "edges": [],
        }
        is_valid, errors = self.validator.validate(workflow)
        assert not is_valid
        assert any(err.code == "DUPLICATE_NODE_ID" for err in errors)

    def test_edge_with_valid_nodes(self):
        """Edge between existing nodes should be valid"""
        workflow = {
            "nodes": [
                {"id": "node_1", "type": "start", "label": "A", "x": 0, "y": 0},
                {"id": "node_2", "type": "end", "label": "B", "x": 100, "y": 100},
            ],
            "edges": [
                {"id": "node_1->node_2", "from": "node_1", "to": "node_2", "label": ""}
            ],
        }
        is_valid, errors = self.validator.validate(workflow)
        assert is_valid
        assert len(errors) == 0

    def test_edge_with_nonexistent_source(self):
        """Edge with non-existent source node should fail"""
        workflow = {
            "nodes": [
                {"id": "node_1", "type": "start", "label": "A", "x": 0, "y": 0},
            ],
            "edges": [
                {"id": "bad->node_1", "from": "nonexistent", "to": "node_1", "label": ""}
            ],
        }
        is_valid, errors = self.validator.validate(workflow)
        assert not is_valid
        assert any(err.code == "INVALID_EDGE_SOURCE" for err in errors)

    def test_edge_with_nonexistent_target(self):
        """Edge with non-existent target node should fail"""
        workflow = {
            "nodes": [
                {"id": "node_1", "type": "start", "label": "A", "x": 0, "y": 0},
            ],
            "edges": [
                {"id": "node_1->bad", "from": "node_1", "to": "nonexistent", "label": ""}
            ],
        }
        is_valid, errors = self.validator.validate(workflow)
        assert not is_valid
        assert any(err.code == "INVALID_EDGE_TARGET" for err in errors)

    def test_duplicate_edge_ids(self):
        """Duplicate edge IDs should fail"""
        workflow = {
            "nodes": [
                {"id": "node_1", "type": "start", "label": "A", "x": 0, "y": 0},
                {"id": "node_2", "type": "end", "label": "B", "x": 100, "y": 100},
            ],
            "edges": [
                {"id": "dup", "from": "node_1", "to": "node_2", "label": ""},
                {"id": "dup", "from": "node_1", "to": "node_2", "label": ""},
            ],
        }
        is_valid, errors = self.validator.validate(workflow)
        assert not is_valid
        assert any(err.code == "DUPLICATE_EDGE_ID" for err in errors)

    def test_decision_node_needs_two_branches(self):
        """Decision node with less than 2 outgoing edges should fail"""
        workflow = {
            "nodes": [
                {"id": "decision", "type": "decision", "label": "Check?", "x": 0, "y": 0},
                {"id": "end", "type": "end", "label": "Result", "x": 100, "y": 100},
            ],
            "edges": [
                {"id": "decision->end", "from": "decision", "to": "end", "label": "true"}
            ],
        }
        is_valid, errors = self.validator.validate(workflow)
        assert not is_valid
        assert any(err.code == "DECISION_NEEDS_BRANCHES" for err in errors)

    def test_decision_node_with_two_branches_valid(self):
        """Decision node with 2 branches should be valid"""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {
                    "id": "decision", 
                    "type": "decision", 
                    "label": "Check?", 
                    "x": 100, 
                    "y": 0,
                    "condition": {"input_id": "var_test", "comparator": "gt", "value": 0}
                },
                {"id": "yes", "type": "end", "label": "Yes", "x": 200, "y": 50},
                {"id": "no", "type": "end", "label": "No", "x": 200, "y": 150},
            ],
            "edges": [
                {"id": "start->decision", "from": "start", "to": "decision", "label": ""},
                {"id": "decision->yes", "from": "decision", "to": "yes", "label": "true"},
                {"id": "decision->no", "from": "decision", "to": "no", "label": "false"},
            ],
            "variables": [{"id": "var_test", "name": "test", "type": "number"}]
        }
        is_valid, errors = self.validator.validate(workflow)
        assert is_valid
        assert len(errors) == 0

    def test_decision_node_missing_true_false_labels(self):
        """Decision node without true/false labels should warn"""
        workflow = {
            "nodes": [
                {"id": "decision", "type": "decision", "label": "Check?", "x": 0, "y": 0},
                {"id": "a", "type": "end", "label": "A", "x": 100, "y": 50},
                {"id": "b", "type": "end", "label": "B", "x": 100, "y": 150},
            ],
            "edges": [
                {"id": "decision->a", "from": "decision", "to": "a", "label": ""},
                {"id": "decision->b", "from": "decision", "to": "b", "label": ""},
            ],
        }
        is_valid, errors = self.validator.validate(workflow)
        assert not is_valid
        assert any(err.code == "DECISION_MISSING_LABELS" for err in errors)

    def test_start_node_with_no_outgoing_edges(self):
        """Start node with no outgoing edges should fail when other nodes exist"""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Input", "x": 0, "y": 0},
                {"id": "end", "type": "end", "label": "Output", "x": 100, "y": 100},
            ],
            "edges": [],
        }
        is_valid, errors = self.validator.validate(workflow)
        assert not is_valid
        assert any(err.code == "START_NO_OUTGOING" for err in errors)

    def test_start_node_with_outgoing_edge_valid(self):
        """Start node with outgoing edge should be valid"""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Input", "x": 0, "y": 0},
                {"id": "end", "type": "end", "label": "Output", "x": 100, "y": 100},
            ],
            "edges": [
                {"id": "start->end", "from": "start", "to": "end", "label": ""}
            ],
        }
        is_valid, errors = self.validator.validate(workflow)
        assert is_valid

    def test_end_node_with_outgoing_edge(self):
        """End node with outgoing edges should fail"""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Input", "x": 0, "y": 0},
                {"id": "end", "type": "end", "label": "Output", "x": 100, "y": 100},
            ],
            "edges": [
                {"id": "start->end", "from": "start", "to": "end", "label": ""},
                {"id": "end->start", "from": "end", "to": "start", "label": ""},
            ],
        }
        is_valid, errors = self.validator.validate(workflow)
        assert not is_valid
        assert any(err.code == "END_HAS_OUTGOING" for err in errors)

    def test_end_node_with_no_outgoing_valid(self):
        """End node with no outgoing edges should be valid"""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Input", "x": 0, "y": 0},
                {"id": "end", "type": "end", "label": "Output", "x": 100, "y": 100},
            ],
            "edges": [
                {"id": "start->end", "from": "start", "to": "end", "label": ""}
            ],
        }
        is_valid, errors = self.validator.validate(workflow)
        assert is_valid

    def test_all_node_types_valid(self):
        """Workflow with all valid node types should pass"""
        workflow = {
            "nodes": [
                {"id": "n1", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "n2", "type": "process", "label": "Process", "x": 100, "y": 0},
                {
                    "id": "n3", 
                    "type": "decision", 
                    "label": "Decision?", 
                    "x": 200, 
                    "y": 0,
                    "condition": {"input_id": "var_test", "comparator": "gt", "value": 0}
                },
                {
                    "id": "n4",
                    "type": "subprocess",
                    "label": "Sub",
                    "x": 300, "y": 0,
                    "subworkflow_id": "wf_test",
                    "input_mapping": {},
                    "output_variable": "Result",
                },
                {"id": "n5", "type": "end", "label": "End1", "x": 400, "y": 0},
                {"id": "n6", "type": "end", "label": "End2", "x": 400, "y": 100},
            ],
            "edges": [
                {"id": "n1->n2", "from": "n1", "to": "n2", "label": ""},
                {"id": "n2->n3", "from": "n2", "to": "n3", "label": ""},
                {"id": "n3->n4", "from": "n3", "to": "n4", "label": "true"},
                {"id": "n3->n5", "from": "n3", "to": "n5", "label": "false"},
                {"id": "n4->n6", "from": "n4", "to": "n6", "label": ""},
            ],
            "variables": [{"id": "var_test", "name": "test", "type": "number"}]
        }
        is_valid, errors = self.validator.validate(workflow)
        assert is_valid
        assert len(errors) == 0

    def test_format_errors_produces_readable_output(self):
        """Error formatter should produce human-readable messages"""
        errors = [
            ValidationError("TEST_ERROR", "This is a test error", node_id="node_1"),
            ValidationError("OTHER_ERROR", "Another error", edge_id="edge_1"),
        ]
        formatted = self.validator.format_errors(errors)
        assert "Workflow validation failed:" in formatted
        assert "This is a test error" in formatted
        assert "node_1" in formatted
        assert "Another error" in formatted
        assert "edge_1" in formatted

    def test_format_errors_empty_list(self):
        """Formatting empty error list should return empty string"""
        formatted = self.validator.format_errors([])
        assert formatted == ""

    def test_multiple_validation_errors(self):
        """Workflow with multiple errors should return all of them"""
        workflow = {
            "nodes": [
                {"id": "bad", "type": "invalid_type", "label": "Bad", "x": 0, "y": 0},
                {"id": "dup", "type": "start", "label": "A", "x": 0, "y": 0},
                {"id": "dup", "type": "end", "label": "B", "x": 100, "y": 0},
            ],
            "edges": [
                {"id": "e1", "from": "bad", "to": "nonexistent", "label": ""}
            ],
        }
        is_valid, errors = self.validator.validate(workflow)
        assert not is_valid
        assert len(errors) >= 3  # Invalid type, duplicate ID, invalid edge target


class TestOutputTypeValidation:
    """Test output_type consistency validation (Rule 14)"""

    def setup_method(self):
        """Setup validator instance for each test"""
        self.validator = WorkflowValidator()

    def test_end_node_output_type_matches_workflow(self):
        """End nodes with matching output_type should pass validation"""
        workflow = {
            "output_type": "float",
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "end", "type": "end", "label": "Result", "x": 100, "y": 0, "output_type": "float"},
            ],
            "edges": [
                {"id": "start->end", "from": "start", "to": "end", "label": ""}
            ],
        }
        is_valid, errors = self.validator.validate(workflow)
        assert is_valid
        assert len(errors) == 0

    def test_end_node_output_type_mismatch_fails(self):
        """End nodes with mismatched output_type should fail validation"""
        workflow = {
            "output_type": "float",
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "end", "type": "end", "label": "Result", "x": 100, "y": 0, "output_type": "string"},
            ],
            "edges": [
                {"id": "start->end", "from": "start", "to": "end", "label": ""}
            ],
        }
        is_valid, errors = self.validator.validate(workflow)
        assert not is_valid
        assert any(err.code == "OUTPUT_TYPE_MISMATCH" for err in errors)

    def test_end_node_default_output_type_is_string(self):
        """End nodes without explicit output_type default to 'string'"""
        workflow = {
            "output_type": "string",
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "end", "type": "end", "label": "Result", "x": 100, "y": 0},  # No output_type specified
            ],
            "edges": [
                {"id": "start->end", "from": "start", "to": "end", "label": ""}
            ],
        }
        is_valid, errors = self.validator.validate(workflow)
        assert is_valid  # Should pass because default is "string"

    def test_end_node_missing_output_type_fails_for_non_string_workflow(self):
        """End nodes without output_type should fail if workflow declares non-string type"""
        workflow = {
            "output_type": "int",
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "end", "type": "end", "label": "Result", "x": 100, "y": 0},  # No output_type, defaults to string
            ],
            "edges": [
                {"id": "start->end", "from": "start", "to": "end", "label": ""}
            ],
        }
        is_valid, errors = self.validator.validate(workflow)
        assert not is_valid
        assert any(err.code == "OUTPUT_TYPE_MISMATCH" for err in errors)
        # Verify error message includes both types
        mismatch_error = next(e for e in errors if e.code == "OUTPUT_TYPE_MISMATCH")
        assert "string" in mismatch_error.message  # Default type
        assert "int" in mismatch_error.message  # Workflow type

    def test_multiple_end_nodes_all_must_match_output_type(self):
        """All end nodes must match workflow output_type"""
        workflow = {
            "output_type": "int",
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {
                    "id": "decision",
                    "type": "decision",
                    "label": "Check",
                    "x": 100, "y": 0,
                    "condition": {"input_id": "var_x", "comparator": "gt", "value": 0}
                },
                {"id": "end1", "type": "end", "label": "High", "x": 200, "y": 0, "output_type": "int"},
                {"id": "end2", "type": "end", "label": "Low", "x": 200, "y": 100, "output_type": "string"},  # Mismatch!
            ],
            "edges": [
                {"id": "start->decision", "from": "start", "to": "decision", "label": ""},
                {"id": "decision->end1", "from": "decision", "to": "end1", "label": "true"},
                {"id": "decision->end2", "from": "decision", "to": "end2", "label": "false"},
            ],
            "variables": [{"id": "var_x", "name": "x", "type": "number"}]
        }
        is_valid, errors = self.validator.validate(workflow)
        assert not is_valid
        # Should have exactly one OUTPUT_TYPE_MISMATCH error for end2
        mismatch_errors = [e for e in errors if e.code == "OUTPUT_TYPE_MISMATCH"]
        assert len(mismatch_errors) == 1
        assert mismatch_errors[0].node_id == "end2"

    def test_multiple_end_nodes_all_matching_passes(self):
        """Workflow with multiple end nodes all matching output_type should pass"""
        workflow = {
            "output_type": "bool",
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {
                    "id": "decision",
                    "type": "decision",
                    "label": "Check",
                    "x": 100, "y": 0,
                    "condition": {"input_id": "var_x", "comparator": "gt", "value": 0}
                },
                {"id": "end1", "type": "end", "label": "True Result", "x": 200, "y": 0, "output_type": "bool"},
                {"id": "end2", "type": "end", "label": "False Result", "x": 200, "y": 100, "output_type": "bool"},
            ],
            "edges": [
                {"id": "start->decision", "from": "start", "to": "decision", "label": ""},
                {"id": "decision->end1", "from": "decision", "to": "end1", "label": "true"},
                {"id": "decision->end2", "from": "decision", "to": "end2", "label": "false"},
            ],
            "variables": [{"id": "var_x", "name": "x", "type": "number"}]
        }
        is_valid, errors = self.validator.validate(workflow)
        assert is_valid
        assert len(errors) == 0

    def test_no_workflow_output_type_skips_validation(self):
        """If workflow has no output_type, end node output_type is not validated"""
        workflow = {
            # No output_type declared at workflow level
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "end", "type": "end", "label": "Result", "x": 100, "y": 0, "output_type": "json"},
            ],
            "edges": [
                {"id": "start->end", "from": "start", "to": "end", "label": ""}
            ],
        }
        is_valid, errors = self.validator.validate(workflow)
        assert is_valid
        # No OUTPUT_TYPE_MISMATCH errors because workflow doesn't declare output_type
        assert not any(e.code == "OUTPUT_TYPE_MISMATCH" for e in errors)

    def test_output_type_validation_only_in_strict_mode(self):
        """Output type validation should only run in strict mode"""
        workflow = {
            "output_type": "float",
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "end", "type": "end", "label": "Result", "x": 100, "y": 0, "output_type": "string"},  # Mismatch
            ],
            "edges": [
                {"id": "start->end", "from": "start", "to": "end", "label": ""}
            ],
        }
        # Strict mode should fail
        is_valid_strict, errors_strict = self.validator.validate(workflow, strict=True)
        assert not is_valid_strict
        assert any(e.code == "OUTPUT_TYPE_MISMATCH" for e in errors_strict)
        
        # Non-strict mode should pass (output_type validation skipped)
        is_valid_lenient, errors_lenient = self.validator.validate(workflow, strict=False)
        assert is_valid_lenient
        assert not any(e.code == "OUTPUT_TYPE_MISMATCH" for e in errors_lenient)

    def test_output_type_json_workflow(self):
        """Workflow with json output_type should validate correctly"""
        workflow = {
            "output_type": "json",
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "end", "type": "end", "label": "JSON Result", "x": 100, "y": 0, "output_type": "json"},
            ],
            "edges": [
                {"id": "start->end", "from": "start", "to": "end", "label": ""}
            ],
        }
        is_valid, errors = self.validator.validate(workflow)
        assert is_valid
        assert len(errors) == 0

