"""Tests for output template variable validation."""

import pytest
from src.backend.validation.workflow_validator import (
    WorkflowValidator,
    ValidationError,
)


class TestOutputTemplateValidation:
    """Test that end/output nodes validate template variables against registered inputs."""

    def setup_method(self):
        """Setup validator instance for each test"""
        self.validator = WorkflowValidator()

    def test_valid_template_with_registered_input(self):
        """Template referencing registered input should be valid."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "end", "type": "end", "label": "Result: {BMI}", "x": 100, "y": 0},
            ],
            "edges": [
                {"id": "start->end", "from": "start", "to": "end", "label": ""},
            ],
            "variables": [
                {"id": "input_bmi_float", "name": "BMI", "type": "float", "description": "Body Mass Index"}
            ]
        }

        is_valid, errors = self.validator.validate(workflow, strict=True)
        template_errors = [e for e in errors if e.code in ("INVALID_TEMPLATE_VARIABLE", "INVALID_LABEL_VARIABLE")]
        assert len(template_errors) == 0, f"Unexpected template errors: {template_errors}"

    def test_invalid_template_with_unregistered_input(self):
        """Template referencing unregistered input should be invalid."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "end", "type": "end", "label": "Result: {UnknownVar}", "x": 100, "y": 0},
            ],
            "edges": [
                {"id": "start->end", "from": "start", "to": "end", "label": ""},
            ],
            "variables": [
                {"id": "input_bmi_float", "name": "BMI", "type": "float", "description": "Body Mass Index"}
            ]
        }

        is_valid, errors = self.validator.validate(workflow, strict=True)
        assert not is_valid
        template_errors = [e for e in errors if e.code == "INVALID_LABEL_VARIABLE"]
        assert len(template_errors) == 1
        assert "UnknownVar" in template_errors[0].message
        assert "BMI" in template_errors[0].message  # Should list available vars

    def test_output_template_field_validation(self):
        """output_template field should be validated for variable references."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {
                    "id": "end", 
                    "type": "end", 
                    "label": "Done",
                    "output_template": "Patient {Name} has BMI {BMI}",
                    "x": 100, 
                    "y": 0
                },
            ],
            "edges": [
                {"id": "start->end", "from": "start", "to": "end", "label": ""},
            ],
            "variables": [
                {"id": "input_bmi_float", "name": "BMI", "type": "float", "description": "Body Mass Index"}
                # "Name" is NOT registered
            ]
        }

        is_valid, errors = self.validator.validate(workflow, strict=True)
        assert not is_valid
        template_errors = [e for e in errors if e.code == "INVALID_TEMPLATE_VARIABLE"]
        assert len(template_errors) == 1
        assert "Name" in template_errors[0].message

    def test_multiple_invalid_variables(self):
        """Multiple unregistered variables should each generate errors."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "end", "type": "end", "label": "{Var1} and {Var2}", "x": 100, "y": 0},
            ],
            "edges": [
                {"id": "start->end", "from": "start", "to": "end", "label": ""},
            ],
            "variables": []  # No variables registered
        }

        is_valid, errors = self.validator.validate(workflow, strict=True)
        assert not is_valid
        template_errors = [e for e in errors if e.code == "INVALID_LABEL_VARIABLE"]
        assert len(template_errors) == 2

    def test_template_with_input_id_reference(self):
        """Template can reference by input ID (e.g., input_bmi_float)."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "end", "type": "end", "label": "Result: {input_bmi_float}", "x": 100, "y": 0},
            ],
            "edges": [
                {"id": "start->end", "from": "start", "to": "end", "label": ""},
            ],
            "variables": [
                {"id": "input_bmi_float", "name": "BMI", "type": "float", "description": "Body Mass Index"}
            ]
        }

        is_valid, errors = self.validator.validate(workflow, strict=True)
        template_errors = [e for e in errors if e.code in ("INVALID_TEMPLATE_VARIABLE", "INVALID_LABEL_VARIABLE")]
        assert len(template_errors) == 0

    def test_plain_label_without_template_valid(self):
        """Labels without template syntax should be valid."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "end", "type": "end", "label": "Process Complete", "x": 100, "y": 0},
            ],
            "edges": [
                {"id": "start->end", "from": "start", "to": "end", "label": ""},
            ],
            "variables": []
        }

        is_valid, errors = self.validator.validate(workflow, strict=True)
        template_errors = [e for e in errors if e.code in ("INVALID_TEMPLATE_VARIABLE", "INVALID_LABEL_VARIABLE")]
        assert len(template_errors) == 0


class TestComparatorValidation:
    """Test that decision conditions validate comparator types."""

    def setup_method(self):
        """Setup validator instance for each test"""
        self.validator = WorkflowValidator()

    def test_valid_comparator_for_float_type(self):
        """Valid comparator for float type should pass."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {
                    "id": "decision", 
                    "type": "decision", 
                    "label": "Check BMI",
                    "condition": {
                        "input_id": "input_bmi_float",
                        "comparator": "gte",
                        "value": 18.5
                    },
                    "x": 100, 
                    "y": 0
                },
                {"id": "yes", "type": "end", "label": "Normal", "x": 200, "y": 50},
                {"id": "no", "type": "end", "label": "Underweight", "x": 200, "y": 150},
            ],
            "edges": [
                {"id": "start->decision", "from": "start", "to": "decision", "label": ""},
                {"id": "decision->yes", "from": "decision", "to": "yes", "label": "true"},
                {"id": "decision->no", "from": "decision", "to": "no", "label": "false"},
            ],
            "variables": [
                {"id": "input_bmi_float", "name": "BMI", "type": "float", "description": "Body Mass Index"}
            ]
        }

        is_valid, errors = self.validator.validate(workflow, strict=True)
        comparator_errors = [e for e in errors if e.code == "INVALID_COMPARATOR_FOR_TYPE"]
        assert len(comparator_errors) == 0

    def test_invalid_comparator_for_float_type(self):
        """Using boolean comparator on float type should fail."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {
                    "id": "decision", 
                    "type": "decision", 
                    "label": "Check BMI",
                    "condition": {
                        "input_id": "input_bmi_float",
                        "comparator": "is_true",  # Invalid for float!
                        "value": None
                    },
                    "x": 100, 
                    "y": 0
                },
                {"id": "yes", "type": "end", "label": "Yes", "x": 200, "y": 50},
                {"id": "no", "type": "end", "label": "No", "x": 200, "y": 150},
            ],
            "edges": [
                {"id": "start->decision", "from": "start", "to": "decision", "label": ""},
                {"id": "decision->yes", "from": "decision", "to": "yes", "label": "true"},
                {"id": "decision->no", "from": "decision", "to": "no", "label": "false"},
            ],
            "variables": [
                {"id": "input_bmi_float", "name": "BMI", "type": "float", "description": "Body Mass Index"}
            ]
        }

        is_valid, errors = self.validator.validate(workflow, strict=True)
        assert not is_valid
        comparator_errors = [e for e in errors if e.code == "INVALID_COMPARATOR_FOR_TYPE"]
        assert len(comparator_errors) == 1
        assert "is_true" in comparator_errors[0].message
        assert "float" in comparator_errors[0].message

    def test_valid_comparator_for_bool_type(self):
        """Valid comparator for bool type should pass."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {
                    "id": "decision", 
                    "type": "decision", 
                    "label": "Is Active?",
                    "condition": {
                        "input_id": "input_is_active_bool",
                        "comparator": "is_true",
                        "value": None
                    },
                    "x": 100, 
                    "y": 0
                },
                {"id": "yes", "type": "end", "label": "Active", "x": 200, "y": 50},
                {"id": "no", "type": "end", "label": "Inactive", "x": 200, "y": 150},
            ],
            "edges": [
                {"id": "start->decision", "from": "start", "to": "decision", "label": ""},
                {"id": "decision->yes", "from": "decision", "to": "yes", "label": "true"},
                {"id": "decision->no", "from": "decision", "to": "no", "label": "false"},
            ],
            "variables": [
                {"id": "input_is_active_bool", "name": "Is Active", "type": "bool", "description": "Whether active"}
            ]
        }

        is_valid, errors = self.validator.validate(workflow, strict=True)
        comparator_errors = [e for e in errors if e.code == "INVALID_COMPARATOR_FOR_TYPE"]
        assert len(comparator_errors) == 0
