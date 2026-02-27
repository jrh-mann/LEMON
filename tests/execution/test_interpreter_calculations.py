"""Tests for calculation node execution in the workflow interpreter."""

import pytest
from src.backend.execution.interpreter import TreeInterpreter, InterpreterError


# ============================================================================
# Test fixtures for calculation workflows
# ============================================================================

# Simple BMI calculation: BMI = weight / (height^2)
BMI_CALCULATION_WORKFLOW = {
    "inputs": [
        {
            "id": "var_weight_number",
            "name": "Weight",
            "type": "number",
            "description": "Weight in kg",
            "range": {"min": 1, "max": 500}
        },
        {
            "id": "var_height_number",
            "name": "Height",
            "type": "number",
            "description": "Height in meters",
            "range": {"min": 0.1, "max": 3.0}
        }
    ],
    "outputs": [
        {"name": "Underweight", "description": "BMI < 18.5"},
        {"name": "Normal", "description": "18.5 <= BMI < 25"},
        {"name": "Overweight", "description": "BMI >= 25"}
    ],
    "tree": {
        "start": {
            "id": "start",
            "type": "start",
            "label": "Start",
            "children": [
                {
                    "id": "calc_height_squared",
                    "type": "calculation",
                    "label": "Height Squared",
                    "calculation": {
                        "output": {"name": "HeightSquared", "description": "Height^2"},
                        "operator": "square",
                        "operands": [
                            {"kind": "variable", "ref": "var_height_number"}
                        ]
                    },
                    "children": [
                        {
                            "id": "calc_bmi",
                            "type": "calculation",
                            "label": "Calculate BMI",
                            "calculation": {
                                "output": {"name": "BMI", "description": "Body Mass Index"},
                                "operator": "divide",
                                "operands": [
                                    {"kind": "variable", "ref": "var_weight_number"},
                                    {"kind": "variable", "ref": "var_calc_heightsquared_number"}
                                ]
                            },
                            "children": [
                                {
                                    "id": "check_underweight",
                                    "type": "decision",
                                    "label": "BMI < 18.5?",
                                    "condition": {
                                        "input_id": "var_calc_bmi_number",
                                        "comparator": "lt",
                                        "value": 18.5
                                    },
                                    "children": [
                                        {
                                            "id": "out_underweight",
                                            "type": "output",
                                            "label": "Underweight",
                                            "edge_label": "Yes",
                                            "children": []
                                        },
                                        {
                                            "id": "check_normal",
                                            "type": "decision",
                                            "label": "BMI < 25?",
                                            "edge_label": "No",
                                            "condition": {
                                                "input_id": "var_calc_bmi_number",
                                                "comparator": "lt",
                                                "value": 25
                                            },
                                            "children": [
                                                {
                                                    "id": "out_normal",
                                                    "type": "output",
                                                    "label": "Normal",
                                                    "edge_label": "Yes",
                                                    "children": []
                                                },
                                                {
                                                    "id": "out_overweight",
                                                    "type": "output",
                                                    "label": "Overweight",
                                                    "edge_label": "No",
                                                    "children": []
                                                }
                                            ]
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    }
}


# Simple addition workflow: sum of three values
SIMPLE_SUM_WORKFLOW = {
    "inputs": [
        {"id": "var_a_number", "name": "A", "type": "number"},
        {"id": "var_b_number", "name": "B", "type": "number"},
        {"id": "var_c_number", "name": "C", "type": "number"}
    ],
    "outputs": [
        {"name": "Large", "description": "Sum >= 100"},
        {"name": "Small", "description": "Sum < 100"}
    ],
    "tree": {
        "start": {
            "id": "start",
            "type": "start",
            "label": "Start",
            "children": [
                {
                    "id": "calc_sum",
                    "type": "calculation",
                    "label": "Calculate Sum",
                    "calculation": {
                        "output": {"name": "Total"},
                        "operator": "add",
                        "operands": [
                            {"kind": "variable", "ref": "var_a_number"},
                            {"kind": "variable", "ref": "var_b_number"},
                            {"kind": "variable", "ref": "var_c_number"}
                        ]
                    },
                    "children": [
                        {
                            "id": "check_large",
                            "type": "decision",
                            "label": "Sum >= 100?",
                            "condition": {
                                "input_id": "var_calc_total_number",
                                "comparator": "gte",
                                "value": 100
                            },
                            "children": [
                                {
                                    "id": "out_large",
                                    "type": "output",
                                    "label": "Large",
                                    "edge_label": "Yes",
                                    "children": []
                                },
                                {
                                    "id": "out_small",
                                    "type": "output",
                                    "label": "Small",
                                    "edge_label": "No",
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


# Literal operand workflow: multiply by constant
LITERAL_OPERAND_WORKFLOW = {
    "inputs": [
        {"id": "var_value_number", "name": "Value", "type": "number"}
    ],
    "outputs": [
        {"name": "Result", "description": "Value * 2.5"}
    ],
    "tree": {
        "start": {
            "id": "start",
            "type": "start",
            "label": "Start",
            "children": [
                {
                    "id": "calc_multiply",
                    "type": "calculation",
                    "label": "Double and Half",
                    "calculation": {
                        "output": {"name": "Result"},
                        "operator": "multiply",
                        "operands": [
                            {"kind": "variable", "ref": "var_value_number"},
                            {"kind": "literal", "value": 2.5}
                        ]
                    },
                    "children": [
                        {
                            "id": "out_result",
                            "type": "output",
                            "label": "Result",
                            "output_template": "{Result}",
                            "children": []
                        }
                    ]
                }
            ]
        }
    }
}


# Chained calculations: average of (a+b, c+d)
CHAINED_CALCULATIONS_WORKFLOW = {
    "inputs": [
        {"id": "var_a_number", "name": "A", "type": "number"},
        {"id": "var_b_number", "name": "B", "type": "number"},
        {"id": "var_c_number", "name": "C", "type": "number"},
        {"id": "var_d_number", "name": "D", "type": "number"}
    ],
    "outputs": [
        {"name": "Average", "description": "Average of sums"}
    ],
    "tree": {
        "start": {
            "id": "start",
            "type": "start",
            "label": "Start",
            "children": [
                {
                    "id": "calc_sum1",
                    "type": "calculation",
                    "label": "Sum A+B",
                    "calculation": {
                        "output": {"name": "Sum1"},
                        "operator": "add",
                        "operands": [
                            {"kind": "variable", "ref": "var_a_number"},
                            {"kind": "variable", "ref": "var_b_number"}
                        ]
                    },
                    "children": [
                        {
                            "id": "calc_sum2",
                            "type": "calculation",
                            "label": "Sum C+D",
                            "calculation": {
                                "output": {"name": "Sum2"},
                                "operator": "add",
                                "operands": [
                                    {"kind": "variable", "ref": "var_c_number"},
                                    {"kind": "variable", "ref": "var_d_number"}
                                ]
                            },
                            "children": [
                                {
                                    "id": "calc_avg",
                                    "type": "calculation",
                                    "label": "Average",
                                    "calculation": {
                                        "output": {"name": "FinalAverage"},
                                        "operator": "average",
                                        "operands": [
                                            {"kind": "variable", "ref": "var_calc_sum1_number"},
                                            {"kind": "variable", "ref": "var_calc_sum2_number"}
                                        ]
                                    },
                                    "children": [
                                        {
                                            "id": "out_result",
                                            "type": "output",
                                            "label": "Average",
                                            "output_template": "{FinalAverage}",
                                            "children": []
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    }
}


class TestCalculationNodeExecution:
    """Test calculation node execution in the interpreter."""

    def test_simple_sum_large(self):
        """Test variadic add operator with large sum."""
        interpreter = TreeInterpreter(
            tree=SIMPLE_SUM_WORKFLOW["tree"],
            inputs=SIMPLE_SUM_WORKFLOW["inputs"],
            outputs=SIMPLE_SUM_WORKFLOW["outputs"]
        )
        result = interpreter.execute({
            "var_a_number": 50.0,
            "var_b_number": 30.0,
            "var_c_number": 25.0
        })
        assert result.success is True
        assert result.output == "Large"
        assert "calc_sum" in result.path

    def test_simple_sum_small(self):
        """Test variadic add operator with small sum."""
        interpreter = TreeInterpreter(
            tree=SIMPLE_SUM_WORKFLOW["tree"],
            inputs=SIMPLE_SUM_WORKFLOW["inputs"],
            outputs=SIMPLE_SUM_WORKFLOW["outputs"]
        )
        result = interpreter.execute({
            "var_a_number": 10.0,
            "var_b_number": 20.0,
            "var_c_number": 30.0
        })
        assert result.success is True
        assert result.output == "Small"

    def test_literal_operand_calculation(self):
        """Test calculation with literal (constant) operand."""
        interpreter = TreeInterpreter(
            tree=LITERAL_OPERAND_WORKFLOW["tree"],
            inputs=LITERAL_OPERAND_WORKFLOW["inputs"],
            outputs=LITERAL_OPERAND_WORKFLOW["outputs"]
        )
        result = interpreter.execute({"var_value_number": 10.0})
        assert result.success is True
        # 10 * 2.5 = 25
        assert result.output == "25.0"

    def test_calculation_output_in_context(self):
        """Test that calculated values are available in context."""
        interpreter = TreeInterpreter(
            tree=SIMPLE_SUM_WORKFLOW["tree"],
            inputs=SIMPLE_SUM_WORKFLOW["inputs"],
            outputs=SIMPLE_SUM_WORKFLOW["outputs"]
        )
        result = interpreter.execute({
            "var_a_number": 10.0,
            "var_b_number": 20.0,
            "var_c_number": 30.0
        })
        assert result.success is True
        # Total should be in context
        assert "var_calc_total_number" in result.context
        assert result.context["var_calc_total_number"] == 60.0


class TestBMICalculationWorkflow:
    """Test BMI calculation workflow with chained calculations."""

    def test_bmi_underweight(self):
        """Test BMI calculation for underweight person."""
        interpreter = TreeInterpreter(
            tree=BMI_CALCULATION_WORKFLOW["tree"],
            inputs=BMI_CALCULATION_WORKFLOW["inputs"],
            outputs=BMI_CALCULATION_WORKFLOW["outputs"]
        )
        # BMI = 50 / (1.8^2) = 50 / 3.24 = 15.43 (underweight)
        result = interpreter.execute({
            "var_weight_number": 50.0,
            "var_height_number": 1.8
        })
        assert result.success is True
        assert result.output == "Underweight"
        # Verify calculation path
        assert "calc_height_squared" in result.path
        assert "calc_bmi" in result.path

    def test_bmi_normal(self):
        """Test BMI calculation for normal weight person."""
        interpreter = TreeInterpreter(
            tree=BMI_CALCULATION_WORKFLOW["tree"],
            inputs=BMI_CALCULATION_WORKFLOW["inputs"],
            outputs=BMI_CALCULATION_WORKFLOW["outputs"]
        )
        # BMI = 70 / (1.75^2) = 70 / 3.0625 = 22.86 (normal)
        result = interpreter.execute({
            "var_weight_number": 70.0,
            "var_height_number": 1.75
        })
        assert result.success is True
        assert result.output == "Normal"

    def test_bmi_overweight(self):
        """Test BMI calculation for overweight person."""
        interpreter = TreeInterpreter(
            tree=BMI_CALCULATION_WORKFLOW["tree"],
            inputs=BMI_CALCULATION_WORKFLOW["inputs"],
            outputs=BMI_CALCULATION_WORKFLOW["outputs"]
        )
        # BMI = 90 / (1.7^2) = 90 / 2.89 = 31.14 (overweight)
        result = interpreter.execute({
            "var_weight_number": 90.0,
            "var_height_number": 1.7
        })
        assert result.success is True
        assert result.output == "Overweight"


class TestChainedCalculations:
    """Test workflows with multiple chained calculation nodes."""

    def test_chained_calculations(self):
        """Test multiple chained calculations."""
        interpreter = TreeInterpreter(
            tree=CHAINED_CALCULATIONS_WORKFLOW["tree"],
            inputs=CHAINED_CALCULATIONS_WORKFLOW["inputs"],
            outputs=CHAINED_CALCULATIONS_WORKFLOW["outputs"]
        )
        # Sum1 = 10 + 20 = 30
        # Sum2 = 30 + 40 = 70
        # Average = (30 + 70) / 2 = 50
        result = interpreter.execute({
            "var_a_number": 10.0,
            "var_b_number": 20.0,
            "var_c_number": 30.0,
            "var_d_number": 40.0
        })
        assert result.success is True
        assert result.output == "50.0"
        # Verify all calculations in path
        assert "calc_sum1" in result.path
        assert "calc_sum2" in result.path
        assert "calc_avg" in result.path
        # Verify intermediate values in context
        assert result.context["var_calc_sum1_number"] == 30.0
        assert result.context["var_calc_sum2_number"] == 70.0
        assert result.context["var_calc_finalaverage_number"] == 50.0


class TestCalculationOnStepCallback:
    """Test on_step callback includes calculation nodes."""

    def test_on_step_includes_calculation_nodes(self):
        """Test that on_step callback is called for calculation nodes."""
        interpreter = TreeInterpreter(
            tree=SIMPLE_SUM_WORKFLOW["tree"],
            inputs=SIMPLE_SUM_WORKFLOW["inputs"],
            outputs=SIMPLE_SUM_WORKFLOW["outputs"]
        )
        
        steps = []
        def on_step(step_info):
            if "step_index" in step_info:
                steps.append(step_info)
        
        result = interpreter.execute({
            "var_a_number": 50.0,
            "var_b_number": 30.0,
            "var_c_number": 25.0
        }, on_step=on_step)
        
        assert result.success is True
        # Should include start, calc_sum, check_large, out_large
        calc_steps = [s for s in steps if s["node_type"] == "calculation"]
        assert len(calc_steps) == 1
        assert calc_steps[0]["node_id"] == "calc_sum"

    def test_on_step_context_includes_calculated_values(self):
        """Test that callback context includes calculated values after calculation node."""
        interpreter = TreeInterpreter(
            tree=SIMPLE_SUM_WORKFLOW["tree"],
            inputs=SIMPLE_SUM_WORKFLOW["inputs"],
            outputs=SIMPLE_SUM_WORKFLOW["outputs"]
        )
        
        steps = []
        def on_step(step_info):
            if "step_index" in step_info:
                steps.append(step_info.copy())
        
        result = interpreter.execute({
            "var_a_number": 10.0,
            "var_b_number": 20.0,
            "var_c_number": 30.0
        }, on_step=on_step)
        
        assert result.success is True
        # After decision node, context should have calculated value
        decision_step = [s for s in steps if s["node_type"] == "decision"][0]
        assert "var_calc_total_number" in decision_step["context"]


class TestCalculationErrorHandling:
    """Test error handling in calculation nodes."""

    def test_division_by_zero_in_calculation(self):
        """Test that division by zero in calculation is handled."""
        # Create a workflow that divides by zero
        divide_by_zero_workflow = {
            "inputs": [
                {"id": "var_a_number", "name": "A", "type": "number"},
                {"id": "var_b_number", "name": "B", "type": "number"}
            ],
            "outputs": [{"name": "Result"}],
            "tree": {
                "start": {
                    "id": "start",
                    "type": "start",
                    "label": "Start",
                    "children": [
                        {
                            "id": "calc_div",
                            "type": "calculation",
                            "label": "Divide",
                            "calculation": {
                                "output": {"name": "Quotient"},
                                "operator": "divide",
                                "operands": [
                                    {"kind": "variable", "ref": "var_a_number"},
                                    {"kind": "variable", "ref": "var_b_number"}
                                ]
                            },
                            "children": [
                                {
                                    "id": "out_result",
                                    "type": "output",
                                    "label": "Result",
                                    "output_template": "{Quotient}",
                                    "children": []
                                }
                            ]
                        }
                    ]
                }
            }
        }
        
        interpreter = TreeInterpreter(
            tree=divide_by_zero_workflow["tree"],
            inputs=divide_by_zero_workflow["inputs"],
            outputs=divide_by_zero_workflow["outputs"]
        )
        result = interpreter.execute({
            "var_a_number": 10.0,
            "var_b_number": 0.0
        })
        assert result.success is False
        assert "Division by zero" in result.error or "divide" in result.error.lower()

    def test_sqrt_of_negative_in_calculation(self):
        """Test that sqrt of negative number in calculation is handled."""
        sqrt_negative_workflow = {
            "inputs": [
                {"id": "var_x_number", "name": "X", "type": "number"}
            ],
            "outputs": [{"name": "Result"}],
            "tree": {
                "start": {
                    "id": "start",
                    "type": "start",
                    "label": "Start",
                    "children": [
                        {
                            "id": "calc_sqrt",
                            "type": "calculation",
                            "label": "Square Root",
                            "calculation": {
                                "output": {"name": "Root"},
                                "operator": "sqrt",
                                "operands": [
                                    {"kind": "variable", "ref": "var_x_number"}
                                ]
                            },
                            "children": [
                                {
                                    "id": "out_result",
                                    "type": "output",
                                    "label": "Result",
                                    "output_template": "{Root}",
                                    "children": []
                                }
                            ]
                        }
                    ]
                }
            }
        }
        
        interpreter = TreeInterpreter(
            tree=sqrt_negative_workflow["tree"],
            inputs=sqrt_negative_workflow["inputs"],
            outputs=sqrt_negative_workflow["outputs"]
        )
        result = interpreter.execute({"var_x_number": -4.0})
        assert result.success is False
        assert "negative" in result.error.lower() or "sqrt" in result.error.lower()
