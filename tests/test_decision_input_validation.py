"""Tests for decision node input validation."""

import pytest
from src.backend.validation.workflow_validator import (
    WorkflowValidator,
    ValidationError,
)


class TestDecisionInputValidation:
    """Test that decision nodes require registered workflow inputs in strict mode."""

    def setup_method(self):
        """Setup validator instance for each test"""
        self.validator = WorkflowValidator()

    def test_decision_without_inputs_valid_in_lenient_mode(self):
        """Decision node without registered inputs should be valid in lenient mode."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "decision", "type": "decision", "label": "age > 18", "x": 100, "y": 0},
                {"id": "yes", "type": "end", "label": "Adult", "x": 200, "y": 50},
                {"id": "no", "type": "end", "label": "Minor", "x": 200, "y": 150},
            ],
            "edges": [
                {"id": "start->decision", "from": "start", "to": "decision", "label": ""},
                {"id": "decision->yes", "from": "decision", "to": "yes", "label": "true"},
                {"id": "decision->no", "from": "decision", "to": "no", "label": "false"},
            ],
            # No inputs field - allows incremental construction
        }

        is_valid, errors = self.validator.validate(workflow, strict=False)
        # Should be valid in lenient mode
        assert is_valid or not any(err.code == "DECISION_MISSING_INPUT" for err in errors)

    def test_decision_without_inputs_invalid_in_strict_mode(self):
        """Decision node without registered inputs should be invalid in strict mode."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "decision", "type": "decision", "label": "age > 18", "x": 100, "y": 0},
                {"id": "yes", "type": "end", "label": "Adult", "x": 200, "y": 50},
                {"id": "no", "type": "end", "label": "Minor", "x": 200, "y": 150},
            ],
            "edges": [
                {"id": "start->decision", "from": "start", "to": "decision", "label": ""},
                {"id": "decision->yes", "from": "decision", "to": "yes", "label": "true"},
                {"id": "decision->no", "from": "decision", "to": "no", "label": "false"},
            ],
            # No inputs field
        }

        is_valid, errors = self.validator.validate(workflow, strict=True)
        assert not is_valid
        assert any(err.code == "DECISION_MISSING_INPUT" for err in errors)

        # Check error message mentions the missing variable
        decision_error = next(err for err in errors if err.code == "DECISION_MISSING_INPUT")
        assert "age" in decision_error.message

    def test_decision_with_unregistered_input_invalid_strict(self):
        """Decision referencing unregistered variable should be invalid in strict mode."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "decision", "type": "decision", "label": "age > 18", "x": 100, "y": 0},
                {"id": "yes", "type": "end", "label": "Adult", "x": 200, "y": 50},
            ],
            "edges": [
                {"id": "start->decision", "from": "start", "to": "decision", "label": ""},
                {"id": "decision->yes", "from": "decision", "to": "yes", "label": "true"},
            ],
            "inputs": [
                {"name": "height", "type": "number", "description": "Height in cm"}
                # 'age' not registered!
            ]
        }

        is_valid, errors = self.validator.validate(workflow, strict=True)
        assert not is_valid
        assert any(err.code == "INVALID_INPUT_REF" for err in errors)

    def test_decision_with_registered_input_valid(self):
        """Decision with properly registered input should be valid."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "decision", "type": "decision", "label": "age > 18", "x": 100, "y": 0},
                {"id": "yes", "type": "end", "label": "Adult", "x": 200, "y": 50},
                {"id": "no", "type": "end", "label": "Minor", "x": 200, "y": 150},
            ],
            "edges": [
                {"id": "start->decision", "from": "start", "to": "decision", "label": ""},
                {"id": "decision->yes", "from": "decision", "to": "yes", "label": "true"},
                {"id": "decision->no", "from": "decision", "to": "no", "label": "false"},
            ],
            "inputs": [
                {"name": "age", "type": "number", "description": "Age in years"}
            ]
        }

        is_valid, errors = self.validator.validate(workflow, strict=True)
        assert is_valid
        assert len(errors) == 0

    def test_multiple_decisions_with_inputs_valid(self):
        """Multiple decision nodes with all inputs registered should be valid."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "d1", "type": "decision", "label": "age > 18", "x": 100, "y": 0},
                {"id": "d2", "type": "decision", "label": "height > 180", "x": 200, "y": 0},
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
            "inputs": [
                {"name": "age", "type": "number", "description": "Age in years"},
                {"name": "height", "type": "number", "description": "Height in cm"}
            ]
        }

        is_valid, errors = self.validator.validate(workflow, strict=True)
        assert is_valid

    def test_decision_with_complex_condition_missing_input_invalid_strict(self):
        """Complex decision condition with missing input should be invalid in strict mode."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "decision", "type": "decision", "label": "age > 18 and height > 180", "x": 100, "y": 0},
                {"id": "end", "type": "end", "label": "End", "x": 200, "y": 0},
            ],
            "edges": [
                {"id": "start->decision", "from": "start", "to": "decision", "label": ""},
                {"id": "decision->end", "from": "decision", "to": "end", "label": "true"},
            ],
            "inputs": [
                {"name": "age", "type": "number", "description": "Age"}
                # 'height' not registered!
            ]
        }

        is_valid, errors = self.validator.validate(workflow, strict=True)
        assert not is_valid
        assert any(err.code == "INVALID_INPUT_REF" for err in errors)

        # Should mention 'height'
        input_errors = [err for err in errors if err.code == "INVALID_INPUT_REF"]
        assert any("height" in err.message for err in input_errors)

    def test_empty_inputs_array_invalid_strict(self):
        """Decision node with empty inputs array should be invalid in strict mode."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "decision", "type": "decision", "label": "age > 18", "x": 100, "y": 0},
                {"id": "end", "type": "end", "label": "End", "x": 200, "y": 0},
            ],
            "edges": [
                {"id": "start->decision", "from": "start", "to": "decision", "label": ""},
                {"id": "decision->end", "from": "decision", "to": "end", "label": "true"},
            ],
            "inputs": []  # Empty array
        }

        is_valid, errors = self.validator.validate(workflow, strict=True)
        assert not is_valid
        assert any(err.code == "INVALID_INPUT_REF" for err in errors)

    def test_decision_invalid_syntax_always_invalid(self):
        """Decision with invalid syntax should be invalid in both modes."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "decision", "type": "decision", "label": "age >>>>>> 18", "x": 100, "y": 0},
                {"id": "end", "type": "end", "label": "End", "x": 200, "y": 0},
            ],
            "edges": [
                {"id": "start->decision", "from": "start", "to": "decision", "label": ""},
                {"id": "decision->end", "from": "decision", "to": "end", "label": "true"},
            ],
        }

        # Invalid in lenient mode
        is_valid_lenient, errors_lenient = self.validator.validate(workflow, strict=False)
        assert not is_valid_lenient
        assert any(err.code == "INVALID_CONDITION_SYNTAX" for err in errors_lenient)

        # Invalid in strict mode
        is_valid_strict, errors_strict = self.validator.validate(workflow, strict=True)
        assert not is_valid_strict
        assert any(err.code == "INVALID_CONDITION_SYNTAX" for err in errors_strict)

    def test_error_message_is_informative(self):
        """Error message should clearly indicate missing input."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "decision", "type": "decision", "label": "temperature > 37.5", "x": 100, "y": 0},
                {"id": "end", "type": "end", "label": "End", "x": 200, "y": 0},
            ],
            "edges": [
                {"id": "start->decision", "from": "start", "to": "decision", "label": ""},
                {"id": "decision->end", "from": "decision", "to": "end", "label": "true"},
            ],
        }

        is_valid, errors = self.validator.validate(workflow, strict=True)
        assert not is_valid

        decision_error = next(err for err in errors if err.code == "DECISION_MISSING_INPUT")
        error_msg = decision_error.message.lower()

        # Should mention the variable name
        assert "temperature" in error_msg
        # Should be actionable
        assert "register" in error_msg or "input" in error_msg
