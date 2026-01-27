"""Tests for workflow input reference validation"""

import pytest
from src.backend.validation.workflow_validator import (
    WorkflowValidator,
    ValidationError,
)


class TestWorkflowValidatorInputs:
    """Test validation of input references in workflow nodes"""

    def setup_method(self):
        """Setup validator instance for each test"""
        self.validator = WorkflowValidator()

    def test_decision_referencing_valid_input(self):
        """Decision node referencing registered input should be valid"""
        workflow = {
            "inputs": [
                {"name": "Age", "type": "int", "id": "input_age"}
            ],
            "nodes": [
                {"id": "s1", "type": "start", "label": "Start", "x": 0, "y": -100},
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
        assert is_valid
        assert len(errors) == 0

    def test_decision_referencing_unregistered_input(self):
        """Decision node referencing unregistered input should fail"""
        workflow = {
            "inputs": [
                {"name": "Height", "type": "int", "id": "input_height"}
            ],
            "nodes": [
                {"id": "s1", "type": "start", "label": "Start", "x": 0, "y": -100},
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
        assert any(err.code == "INVALID_INPUT_REF" for err in errors)
        assert any("Age" in err.message for err in errors)

    def test_decision_referencing_multiple_inputs(self):
        """Decision node referencing multiple inputs"""
        workflow = {
            "inputs": [
                {"name": "Age", "type": "int", "id": "input_age"},
                {"name": "Smoker", "type": "bool", "id": "input_smoker"}
            ],
            "nodes": [
                {"id": "s1", "type": "start", "label": "Start", "x": 0, "y": -100},
                {"id": "d1", "type": "decision", "label": "Age > 18 and Smoker == True", "x": 0, "y": 0},
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

    def test_decision_referencing_mixed_validity(self):
        """Decision node referencing one valid and one invalid input"""
        workflow = {
            "inputs": [
                {"name": "Age", "type": "int", "id": "input_age"}
            ],
            "nodes": [
                {"id": "s1", "type": "start", "label": "Start", "x": 0, "y": -100},
                {"id": "d1", "type": "decision", "label": "Age > 18 and Smoker == True", "x": 0, "y": 0},
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
        assert any(err.code == "INVALID_INPUT_REF" for err in errors)
        assert any("Smoker" in err.message for err in errors)

    def test_decision_with_invalid_condition_input_fails(self):
        """Decision node with structured condition referencing unknown input_id should fail."""
        workflow = {
            "inputs": [{"name": "Age", "type": "int", "id": "input_age_int"}],
            "nodes": [
                {"id": "s1", "type": "start", "label": "Start", "x": 0, "y": -100},
                {
                    "id": "d1", 
                    "type": "decision", 
                    "label": "BMI Check", 
                    "x": 0, 
                    "y": 0,
                    "condition": {
                        "input_id": "input_bmi_float",  # Does not exist in inputs
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

    def test_decision_descriptive_label_without_condition_allowed(self):
        """Decision node without condition can have descriptive label (backwards compat)."""
        workflow = {
            "inputs": [{"name": "Age", "type": "int", "id": "input_age_int"}],
            "nodes": [
                {"id": "s1", "type": "start", "label": "Start", "x": 0, "y": -100},
                # No condition field - label is descriptive, not a condition expression
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
        # Descriptive labels are allowed when no structured condition exists
        is_valid, errors = self.validator.validate(workflow)
        assert is_valid
