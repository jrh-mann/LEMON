"""Tests for numeric output type preservation in subworkflows.

This tests the bug where a subworkflow with output_type='number' returns
a string instead of a float, causing var_sub_bmi_string instead of
var_sub_bmi_number in the parent workflow.

Root cause: When end nodes use output_template like "{BMI}", the value
was always formatted as a string regardless of output_type.

Fix: _resolve_output_value now respects output_type and:
1. For single variable templates like "{BMI}", returns raw value with type cast
2. For complex templates, casts the result to the declared type
"""

import pytest
from src.backend.execution.interpreter import TreeInterpreter


class TestNumericOutputType:
    """Test that output_type='number' returns actual float, not string."""

    def test_single_variable_template_returns_number(self):
        """When output_template is "{VarName}" and output_type is 'number', return float."""
        # Simple workflow: take a number, double it, return it
        workflow = {
            "inputs": [
                {
                    "id": "var_value_number",
                    "name": "Value",
                    "type": "number",
                    "range": {"min": 0, "max": 1000}
                }
            ],
            "outputs": [
                {"name": "Result", "type": "number", "description": "Doubled value"}
            ],
            "tree": {
                "start": {
                    "id": "start",
                    "type": "start",
                    "label": "Start",
                    "children": [
                        {
                            "id": "calc_double",
                            "type": "calculation",
                            "label": "Double Value",
                            "calculation": {
                                "output": {"name": "Result"},
                                "operator": "multiply",
                                "operands": [
                                    {"kind": "variable", "ref": "Value"},
                                    {"kind": "literal", "value": 2}
                                ]
                            },
                            "children": [
                                {
                                    "id": "end_result",
                                    "type": "output",
                                    "label": "Return Result",
                                    "output_type": "number",  # Declares numeric output
                                    "output_template": "{Result}",  # Single var template
                                    "children": []
                                }
                            ]
                        }
                    ]
                }
            }
        }

        interpreter = TreeInterpreter(
            tree=workflow["tree"],
            inputs=workflow["inputs"],
            outputs=workflow["outputs"],
            output_type="number"
        )

        result = interpreter.execute({"var_value_number": 25.5})

        assert result.success is True, f"Execution failed: {result.error}"
        
        # Critical: output should be float, not string
        assert isinstance(result.output, float), (
            f"Expected float output, got {type(result.output).__name__}: {result.output}"
        )
        
        # Check value is correct (25.5 * 2 = 51.0)
        assert result.output == 51.0, f"Expected 51.0, got {result.output}"

    def test_complex_template_with_number_type_returns_number(self):
        """When output_template produces a number string and output_type is 'number', cast it."""
        workflow = {
            "inputs": [
                {
                    "id": "var_age_number",
                    "name": "Age",
                    "type": "number",
                    "range": {"min": 0, "max": 120}
                }
            ],
            "outputs": [
                {"name": "AgeValue", "type": "number"}
            ],
            "tree": {
                "start": {
                    "id": "start",
                    "type": "start",
                    "label": "Start",
                    "children": [
                        {
                            "id": "end_age",
                            "type": "output",
                            "label": "Return Age",
                            "output_type": "number",
                            "output_template": "{Age}",  # Just return the age
                            "children": []
                        }
                    ]
                }
            }
        }

        interpreter = TreeInterpreter(
            tree=workflow["tree"],
            inputs=workflow["inputs"],
            outputs=workflow["outputs"],
            output_type="number"
        )

        result = interpreter.execute({"var_age_number": 25})

        assert result.success is True
        assert isinstance(result.output, float), (
            f"Expected float, got {type(result.output).__name__}: {result.output}"
        )
        assert result.output == 25.0

    def test_string_output_type_still_returns_string(self):
        """When output_type is 'string', output_template result stays as string."""
        workflow = {
            "inputs": [
                {
                    "id": "var_name_string",
                    "name": "Name",
                    "type": "string"
                }
            ],
            "outputs": [
                {"name": "Greeting", "type": "string"}
            ],
            "tree": {
                "start": {
                    "id": "start",
                    "type": "start",
                    "label": "Start",
                    "children": [
                        {
                            "id": "end_greet",
                            "type": "output",
                            "label": "Greet",
                            "output_type": "string",
                            "output_template": "Hello, {Name}!",
                            "children": []
                        }
                    ]
                }
            }
        }

        interpreter = TreeInterpreter(
            tree=workflow["tree"],
            inputs=workflow["inputs"],
            outputs=workflow["outputs"]
        )

        result = interpreter.execute({"var_name_string": "Alice"})

        assert result.success is True
        assert isinstance(result.output, str)
        assert result.output == "Hello, Alice!"

    def test_bool_output_type_returns_bool(self):
        """When output_type is 'bool' and template produces 'true'/'false', return bool."""
        workflow = {
            "inputs": [
                {
                    "id": "var_flag_bool",
                    "name": "Flag",
                    "type": "bool"
                }
            ],
            "outputs": [
                {"name": "Result", "type": "bool"}
            ],
            "tree": {
                "start": {
                    "id": "start",
                    "type": "start",
                    "label": "Start",
                    "children": [
                        {
                            "id": "end_flag",
                            "type": "output",
                            "label": "Return Flag",
                            "output_type": "bool",
                            "output_template": "{Flag}",
                            "children": []
                        }
                    ]
                }
            }
        }

        interpreter = TreeInterpreter(
            tree=workflow["tree"],
            inputs=workflow["inputs"],
            outputs=workflow["outputs"],
            output_type="bool"
        )

        result = interpreter.execute({"var_flag_bool": True})

        assert result.success is True
        assert isinstance(result.output, bool), (
            f"Expected bool, got {type(result.output).__name__}: {result.output}"
        )
        assert result.output is True


class TestSubworkflowNumericOutputType:
    """Test that subworkflow numeric outputs are correctly typed in parent context."""

    def test_subprocess_output_is_number_when_subworkflow_returns_number(self):
        """When subworkflow returns a number, parent gets var_sub_*_number, not _string."""
        # This simulates a simple doubling subworkflow that returns a numeric value
        # The parent should get var_sub_result_number in context

        class MockWorkflowStore:
            class MockSubworkflow:
                id = "wf_doubler"
                name = "Value Doubler"
                inputs = [
                    {"id": "var_value_number", "name": "Value", "type": "number"},
                ]
                outputs = [{"name": "Result", "type": "number"}]
                nodes = []
                edges = []
                output_type = "number"

                # The tree that doubles and returns as a number
                tree = {
                    "start": {
                        "id": "start",
                        "type": "start",
                        "label": "Start",
                        "children": [
                            {
                                "id": "calc_double",
                                "type": "calculation",
                                "label": "Double Value",
                                "calculation": {
                                    "output": {"name": "Result"},
                                    "operator": "multiply",
                                    "operands": [
                                        {"kind": "variable", "ref": "Value"},
                                        {"kind": "literal", "value": 2}
                                    ]
                                },
                                "children": [
                                    {
                                        "id": "end_result",
                                        "type": "output",
                                        "label": "Return Result",
                                        "output_type": "number",
                                        "output_template": "{Result}",
                                        "children": []
                                    }
                                ]
                            }
                        ]
                    }
                }

            def get_workflow(self, workflow_id, user_id):
                if workflow_id == "wf_doubler":
                    return self.MockSubworkflow()
                return None

        # Parent workflow that calls doubler then uses the result in a decision
        parent_workflow = {
            "inputs": [
                {"id": "var_value_number", "name": "Value", "type": "number"},
            ],
            "outputs": [
                {"name": "Category", "type": "string"}
            ],
            "tree": {
                "start": {
                    "id": "start",
                    "type": "start",
                    "label": "Start",
                    "children": [
                        {
                            "id": "subprocess_double",
                            "type": "subprocess",
                            "label": "Double Value",
                            "subworkflow_id": "wf_doubler",
                            "input_mapping": {
                                "Value": "Value"
                            },
                            "output_variable": "DoubledValue",
                            "children": [
                                {
                                    "id": "check_threshold",
                                    "type": "decision",
                                    "label": "Result >= 100?",
                                    "input_ids": ["var_sub_doubledvalue_number"],
                                    "condition": {
                                        "input_id": "var_sub_doubledvalue_number",
                                        "comparator": "gte",
                                        "value": 100
                                    },
                                    "children": [
                                        {
                                            "id": "out_high",
                                            "type": "output",
                                            "label": "High",
                                            "edge_label": "true",
                                            "children": []
                                        },
                                        {
                                            "id": "out_low",
                                            "type": "output",
                                            "label": "Low",
                                            "edge_label": "false",
                                            "children": []
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            }
        }

        interpreter = TreeInterpreter(
            tree=parent_workflow["tree"],
            inputs=parent_workflow["inputs"],
            outputs=parent_workflow["outputs"],
            workflow_store=MockWorkflowStore(),
            user_id="test_user"
        )

        # Execute with value=60 → doubled = 120 → >= 100 → "High"
        result = interpreter.execute({"var_value_number": 60})

        assert result.success is True, f"Execution failed: {result.error}"
        
        # Check that subprocess output is in context with correct type
        assert "var_sub_doubledvalue_number" in result.context, (
            f"Expected var_sub_doubledvalue_number in context, got keys: {list(result.context.keys())}"
        )
        
        # The value should be a float, not a string
        doubled_value = result.context["var_sub_doubledvalue_number"]
        assert isinstance(doubled_value, float), (
            f"Expected float for var_sub_doubledvalue_number, got {type(doubled_value).__name__}: {doubled_value}"
        )
        
        assert doubled_value == 120.0
        
        # Decision should take True branch (120 >= 100)
        assert result.output == "High", (
            f"Expected 'High' for doubled={doubled_value}, got '{result.output}'"
        )

    def test_subprocess_output_low_case(self):
        """Test that low values correctly take false branch."""
        class MockWorkflowStore:
            class MockSubworkflow:
                id = "wf_doubler"
                name = "Value Doubler"
                inputs = [
                    {"id": "var_value_number", "name": "Value", "type": "number"},
                ]
                outputs = [{"name": "Result", "type": "number"}]
                nodes = []
                edges = []
                output_type = "number"
                tree = {
                    "start": {
                        "id": "start",
                        "type": "start",
                        "label": "Start",
                        "children": [
                            {
                                "id": "calc_double",
                                "type": "calculation",
                                "label": "Double Value",
                                "calculation": {
                                    "output": {"name": "Result"},
                                    "operator": "multiply",
                                    "operands": [
                                        {"kind": "variable", "ref": "Value"},
                                        {"kind": "literal", "value": 2}
                                    ]
                                },
                                "children": [
                                    {
                                        "id": "end_result",
                                        "type": "output",
                                        "label": "Return Result",
                                        "output_type": "number",
                                        "output_template": "{Result}",
                                        "children": []
                                    }
                                ]
                            }
                        ]
                    }
                }

            def get_workflow(self, workflow_id, user_id):
                if workflow_id == "wf_doubler":
                    return self.MockSubworkflow()
                return None

        parent_workflow = {
            "inputs": [
                {"id": "var_value_number", "name": "Value", "type": "number"},
            ],
            "outputs": [{"name": "Category", "type": "string"}],
            "tree": {
                "start": {
                    "id": "start",
                    "type": "start",
                    "label": "Start",
                    "children": [
                        {
                            "id": "subprocess_double",
                            "type": "subprocess",
                            "label": "Double Value",
                            "subworkflow_id": "wf_doubler",
                            "input_mapping": {"Value": "Value"},
                            "output_variable": "DoubledValue",
                            "children": [
                                {
                                    "id": "check_threshold",
                                    "type": "decision",
                                    "label": "Result >= 100?",
                                    "input_ids": ["var_sub_doubledvalue_number"],
                                    "condition": {
                                        "input_id": "var_sub_doubledvalue_number",
                                        "comparator": "gte",
                                        "value": 100
                                    },
                                    "children": [
                                        {
                                            "id": "out_high",
                                            "type": "output",
                                            "label": "High",
                                            "edge_label": "true",
                                            "children": []
                                        },
                                        {
                                            "id": "out_low",
                                            "type": "output",
                                            "label": "Low",
                                            "edge_label": "false",
                                            "children": []
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            }
        }

        interpreter = TreeInterpreter(
            tree=parent_workflow["tree"],
            inputs=parent_workflow["inputs"],
            outputs=parent_workflow["outputs"],
            workflow_store=MockWorkflowStore(),
            user_id="test_user"
        )

        # Execute with value=30 → doubled = 60 → < 100 → "Low"
        result = interpreter.execute({"var_value_number": 30})

        assert result.success is True, f"Execution failed: {result.error}"
        
        doubled_value = result.context.get("var_sub_doubledvalue_number")
        
        assert isinstance(doubled_value, float)
        assert doubled_value == 60.0
        
        # Decision should take False branch (60 < 100)
        assert result.output == "Low", (
            f"Expected 'Low' for doubled={doubled_value}, got '{result.output}'"
        )
