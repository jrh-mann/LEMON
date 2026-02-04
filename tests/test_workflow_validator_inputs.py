"""Tests for workflow variable reference validation in structured conditions.

Decision nodes MUST have a structured `condition` field that references variables by ID.
Workflows use `variables` (not `inputs`) to store variable definitions.
"""

import pytest
from src.backend.validation.workflow_validator import (
    WorkflowValidator,
    ValidationError,
)


class TestWorkflowValidatorInputs:
    """Test validation of variable references in workflow decision conditions."""

    def setup_method(self):
        """Setup validator instance for each test"""
        self.validator = WorkflowValidator()

    def test_decision_with_valid_condition_referencing_registered_variable(self):
        """Decision node with condition referencing registered variable should be valid."""
        workflow = {
            "variables": [
                {"name": "Age", "type": "number", "id": "input_age"}
            ],
            "nodes": [
                {"id": "s1", "type": "start", "label": "Start", "x": 0, "y": -100},
                {
                    "id": "d1", 
                    "type": "decision", 
                    "label": "Age Check", 
                    "x": 0, 
                    "y": 0,
                    "condition": {
                        "input_id": "input_age",
                        "comparator": "gt",
                        "value": 18
                    }
                },
                {"id": "y", "type": "end", "label": "Yes", "x": 100, "y": 0},
                {"id": "n", "type": "end", "label": "No", "x": 100, "y": 100},
            ],
            "edges": [
                {"from": "s1", "to": "d1", "label": ""},
                {"from": "d1", "to": "y", "label": "true"},
                {"from": "d1", "to": "n", "label": "false"},
            ]
        }
        is_valid, errors = self.validator.validate(workflow)
        assert is_valid
        assert len(errors) == 0

    def test_decision_with_condition_referencing_unregistered_variable(self):
        """Decision node with condition referencing unregistered variable should fail."""
        workflow = {
            "variables": [
                {"name": "Height", "type": "number", "id": "input_height"}
            ],
            "nodes": [
                {"id": "s1", "type": "start", "label": "Start", "x": 0, "y": -100},
                {
                    "id": "d1", 
                    "type": "decision", 
                    "label": "Age Check", 
                    "x": 0, 
                    "y": 0,
                    "condition": {
                        "input_id": "input_age",  # Not registered
                        "comparator": "gt",
                        "value": 18
                    }
                },
                {"id": "y", "type": "end", "label": "Yes", "x": 100, "y": 0},
                {"id": "n", "type": "end", "label": "No", "x": 100, "y": 100},
            ],
            "edges": [
                {"from": "s1", "to": "d1", "label": ""},
                {"from": "d1", "to": "y", "label": "true"},
                {"from": "d1", "to": "n", "label": "false"},
            ]
        }
        is_valid, errors = self.validator.validate(workflow)
        assert not is_valid
        assert any(err.code == "INVALID_CONDITION_INPUT_ID" for err in errors)

    def test_multiple_decisions_with_valid_conditions(self):
        """Multiple decision nodes with valid conditions referencing registered variables."""
        workflow = {
            "variables": [
                {"name": "Age", "type": "number", "id": "input_age"},
                {"name": "Smoker", "type": "bool", "id": "input_smoker"}
            ],
            "nodes": [
                {"id": "s1", "type": "start", "label": "Start", "x": 0, "y": -100},
                {
                    "id": "d1", 
                    "type": "decision", 
                    "label": "Age Check", 
                    "x": 0, 
                    "y": 0,
                    "condition": {
                        "input_id": "input_age",
                        "comparator": "gt",
                        "value": 18
                    }
                },
                {
                    "id": "d2", 
                    "type": "decision", 
                    "label": "Smoker Check", 
                    "x": 0, 
                    "y": 100,
                    "condition": {
                        "input_id": "input_smoker",
                        "comparator": "is_true",
                        "value": None
                    }
                },
                {"id": "y", "type": "end", "label": "Yes", "x": 100, "y": 0},
                {"id": "n", "type": "end", "label": "No", "x": 100, "y": 100},
            ],
            "edges": [
                {"from": "s1", "to": "d1", "label": ""},
                {"from": "d1", "to": "d2", "label": "true"},
                {"from": "d1", "to": "n", "label": "false"},
                {"from": "d2", "to": "y", "label": "true"},
                {"from": "d2", "to": "n", "label": "false"},
            ]
        }
        is_valid, errors = self.validator.validate(workflow)
        assert is_valid

    def test_decision_without_condition_fails(self):
        """Decision node without structured condition should fail validation."""
        workflow = {
            "variables": [
                {"name": "Age", "type": "number", "id": "input_age"}
            ],
            "nodes": [
                {"id": "s1", "type": "start", "label": "Start", "x": 0, "y": -100},
                # No condition field - this is now invalid
                {"id": "d1", "type": "decision", "label": "Age > 18", "x": 0, "y": 0},
                {"id": "y", "type": "end", "label": "Yes", "x": 100, "y": 0},
                {"id": "n", "type": "end", "label": "No", "x": 100, "y": 100},
            ],
            "edges": [
                {"from": "s1", "to": "d1", "label": ""},
                {"from": "d1", "to": "y", "label": "true"},
                {"from": "d1", "to": "n", "label": "false"},
            ]
        }
        is_valid, errors = self.validator.validate(workflow)
        assert not is_valid
        assert any(err.code == "MISSING_CONDITION" for err in errors)

    def test_decision_with_invalid_condition_input_fails(self):
        """Decision node with structured condition referencing unknown input_id should fail."""
        workflow = {
            "variables": [{"name": "Age", "type": "number", "id": "input_age_int"}],
            "nodes": [
                {"id": "s1", "type": "start", "label": "Start", "x": 0, "y": -100},
                {
                    "id": "d1", 
                    "type": "decision", 
                    "label": "BMI Check", 
                    "x": 0, 
                    "y": 0,
                    "condition": {
                        "input_id": "input_bmi_float",  # Does not exist in variables
                        "comparator": "gt",
                        "value": 25
                    }
                },
                {"id": "y", "type": "end", "label": "Yes", "x": 100, "y": 0},
                {"id": "n", "type": "end", "label": "No", "x": 100, "y": 100},
            ],
            "edges": [
                {"from": "s1", "to": "d1", "label": ""},
                {"from": "d1", "to": "y", "label": "true"},
                {"from": "d1", "to": "n", "label": "false"},
            ]
        }
        is_valid, errors = self.validator.validate(workflow)
        assert not is_valid
        assert any(err.code == "INVALID_CONDITION_INPUT_ID" for err in errors)

    def test_decision_with_descriptive_label_but_no_condition_fails(self):
        """Decision node with descriptive label but no condition field should fail."""
        workflow = {
            "variables": [{"name": "Age", "type": "number", "id": "input_age_int"}],
            "nodes": [
                {"id": "s1", "type": "start", "label": "Start", "x": 0, "y": -100},
                # No condition field - descriptive labels are no longer allowed without condition
                {"id": "d1", "type": "decision", "label": "Check eligibility criteria", "x": 0, "y": 0},
                {"id": "y", "type": "end", "label": "Yes", "x": 100, "y": 0},
                {"id": "n", "type": "end", "label": "No", "x": 100, "y": 100},
            ],
            "edges": [
                {"from": "s1", "to": "d1", "label": ""},
                {"from": "d1", "to": "y", "label": "true"},
                {"from": "d1", "to": "n", "label": "false"},
            ]
        }
        # Descriptive labels without conditions are now invalid
        is_valid, errors = self.validator.validate(workflow)
        assert not is_valid
        assert any(err.code == "MISSING_CONDITION" for err in errors)
