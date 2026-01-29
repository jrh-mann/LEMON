"""Tests for decision node input validation with structured conditions.

Decision nodes MUST have a structured `condition` field containing:
- input_id: ID of a registered variable
- comparator: Comparison operator (eq, neq, gt, gte, lt, lte, contains, etc.)
- value: Value to compare against

Decision nodes WITHOUT a condition field will fail validation with MISSING_CONDITION error.
"""

import pytest
from src.backend.validation.workflow_validator import (
    WorkflowValidator,
    ValidationError,
)


class TestDecisionInputValidation:
    """Test that decision nodes require structured conditions with valid input references."""

    def setup_method(self):
        """Setup validator instance for each test"""
        self.validator = WorkflowValidator()

    def test_decision_without_condition_invalid_lenient_mode(self):
        """Decision node without condition field should fail even in lenient mode."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                # No condition field - this is now invalid
                {"id": "decision", "type": "decision", "label": "age > 18", "x": 100, "y": 0},
                {"id": "yes", "type": "end", "label": "Adult", "x": 200, "y": 50},
                {"id": "no", "type": "end", "label": "Minor", "x": 200, "y": 150},
            ],
            "edges": [
                {"id": "start->decision", "from": "start", "to": "decision", "label": ""},
                {"id": "decision->yes", "from": "decision", "to": "yes", "label": "true"},
                {"id": "decision->no", "from": "decision", "to": "no", "label": "false"},
            ],
            "variables": [],
        }

        is_valid, errors = self.validator.validate(workflow, strict=False)
        assert not is_valid
        assert any(err.code == "MISSING_CONDITION" for err in errors)

    def test_decision_without_condition_invalid_strict_mode(self):
        """Decision node without condition field should fail in strict mode."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "decision", "type": "decision", "label": "Check something", "x": 100, "y": 0},
                {"id": "yes", "type": "end", "label": "Yes", "x": 200, "y": 50},
                {"id": "no", "type": "end", "label": "No", "x": 200, "y": 150},
            ],
            "edges": [
                {"id": "start->decision", "from": "start", "to": "decision", "label": ""},
                {"id": "decision->yes", "from": "decision", "to": "yes", "label": "true"},
                {"id": "decision->no", "from": "decision", "to": "no", "label": "false"},
            ],
            "variables": [],
        }

        is_valid, errors = self.validator.validate(workflow, strict=True)
        assert not is_valid
        assert any(err.code == "MISSING_CONDITION" for err in errors)
        
        # Error should identify the problematic node
        condition_error = next(err for err in errors if err.code == "MISSING_CONDITION")
        assert condition_error.node_id == "decision"

    def test_decision_with_valid_condition_and_registered_variable(self):
        """Decision with proper condition referencing registered variable should be valid."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {
                    "id": "decision", 
                    "type": "decision", 
                    "label": "Age Check", 
                    "x": 100, 
                    "y": 0,
                    "condition": {
                        "input_id": "var_age",
                        "comparator": "gt",
                        "value": 18
                    }
                },
                {"id": "yes", "type": "end", "label": "Adult", "x": 200, "y": 50},
                {"id": "no", "type": "end", "label": "Minor", "x": 200, "y": 150},
            ],
            "edges": [
                {"id": "start->decision", "from": "start", "to": "decision", "label": ""},
                {"id": "decision->yes", "from": "decision", "to": "yes", "label": "true"},
                {"id": "decision->no", "from": "decision", "to": "no", "label": "false"},
            ],
            "variables": [
                {"id": "var_age", "name": "age", "type": "int", "description": "Age in years"}
            ]
        }

        is_valid, errors = self.validator.validate(workflow, strict=True)
        assert is_valid
        assert len(errors) == 0

    def test_decision_with_condition_referencing_unknown_variable(self):
        """Decision condition referencing non-existent variable should fail."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {
                    "id": "decision", 
                    "type": "decision", 
                    "label": "Age Check", 
                    "x": 100, 
                    "y": 0,
                    "condition": {
                        "input_id": "var_age",  # References non-existent variable
                        "comparator": "gt",
                        "value": 18
                    }
                },
                {"id": "yes", "type": "end", "label": "Adult", "x": 200, "y": 0},
                {"id": "no", "type": "end", "label": "Minor", "x": 200, "y": 100},
            ],
            "edges": [
                {"id": "start->decision", "from": "start", "to": "decision", "label": ""},
                {"id": "decision->yes", "from": "decision", "to": "yes", "label": "true"},
                {"id": "decision->no", "from": "decision", "to": "no", "label": "false"},
            ],
            # Has a variable but NOT the one the condition references
            "variables": [{"id": "var_bmi", "name": "BMI", "type": "float"}]
        }

        is_valid, errors = self.validator.validate(workflow, strict=True)
        assert not is_valid
        assert any(err.code == "INVALID_CONDITION_INPUT_ID" for err in errors)

    def test_multiple_decisions_with_valid_conditions(self):
        """Multiple decision nodes with valid conditions should be valid."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {
                    "id": "d1", 
                    "type": "decision", 
                    "label": "Age Check",
                    "x": 100, 
                    "y": 0,
                    "condition": {"input_id": "var_age", "comparator": "gt", "value": 18}
                },
                {
                    "id": "d2", 
                    "type": "decision", 
                    "label": "Height Check",
                    "x": 200, 
                    "y": 0,
                    "condition": {"input_id": "var_height", "comparator": "gt", "value": 180}
                },
                {"id": "end1", "type": "end", "label": "End 1", "x": 300, "y": 0},
                {"id": "end2", "type": "end", "label": "End 2", "x": 300, "y": 100},
            ],
            "edges": [
                {"id": "start->d1", "from": "start", "to": "d1", "label": ""},
                {"id": "d1->d2", "from": "d1", "to": "d2", "label": "true"},
                {"id": "d1->end1", "from": "d1", "to": "end1", "label": "false"},
                {"id": "d2->end1", "from": "d2", "to": "end1", "label": "true"},
                {"id": "d2->end2", "from": "d2", "to": "end2", "label": "false"},
            ],
            "variables": [
                {"id": "var_age", "name": "age", "type": "int", "description": "Age in years"},
                {"id": "var_height", "name": "height", "type": "int", "description": "Height in cm"}
            ]
        }

        is_valid, errors = self.validator.validate(workflow, strict=True)
        assert is_valid

    def test_decision_condition_missing_input_id(self):
        """Condition without input_id field should fail validation."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {
                    "id": "decision", 
                    "type": "decision", 
                    "label": "Check", 
                    "x": 100, 
                    "y": 0,
                    "condition": {
                        # Missing input_id
                        "comparator": "gt",
                        "value": 18
                    }
                },
                {"id": "end", "type": "end", "label": "End", "x": 200, "y": 0},
            ],
            "edges": [
                {"id": "start->decision", "from": "start", "to": "decision", "label": ""},
                {"id": "decision->end", "from": "decision", "to": "end", "label": "true"},
            ],
            "variables": []
        }

        is_valid, errors = self.validator.validate(workflow, strict=True)
        assert not is_valid
        # Should fail because condition is missing input_id
        assert any(err.code == "MISSING_CONDITION_INPUT_ID" for err in errors)

    def test_decision_condition_missing_comparator(self):
        """Condition without comparator field should fail validation."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {
                    "id": "decision", 
                    "type": "decision", 
                    "label": "Check", 
                    "x": 100, 
                    "y": 0,
                    "condition": {
                        "input_id": "var_age",
                        # Missing comparator
                        "value": 18
                    }
                },
                {"id": "end", "type": "end", "label": "End", "x": 200, "y": 0},
            ],
            "edges": [
                {"id": "start->decision", "from": "start", "to": "decision", "label": ""},
                {"id": "decision->end", "from": "decision", "to": "end", "label": "true"},
            ],
            "variables": [{"id": "var_age", "name": "age", "type": "int"}]
        }

        is_valid, errors = self.validator.validate(workflow, strict=True)
        assert not is_valid
        assert any(err.code == "MISSING_CONDITION_COMPARATOR" for err in errors)

    def test_error_message_identifies_problematic_node(self):
        """Error message should clearly identify the decision node missing condition."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "my_decision_node", "type": "decision", "label": "Some Check", "x": 100, "y": 0},
                {"id": "end", "type": "end", "label": "End", "x": 200, "y": 0},
            ],
            "edges": [
                {"id": "start->decision", "from": "start", "to": "my_decision_node", "label": ""},
                {"id": "decision->end", "from": "my_decision_node", "to": "end", "label": "true"},
            ],
            "variables": [],
        }

        is_valid, errors = self.validator.validate(workflow, strict=True)
        assert not is_valid

        condition_error = next(err for err in errors if err.code == "MISSING_CONDITION")
        # Error should identify the node
        assert condition_error.node_id == "my_decision_node"
