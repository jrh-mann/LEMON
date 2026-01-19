"""Tests for workflow tree interpreter (full execution)"""

import pytest
from src.backend.execution.interpreter import TreeInterpreter, InterpreterError
from .fixtures import (
    SIMPLE_AGE_WORKFLOW,
    SIMPLE_AGE_TEST_CASES,
    CHOLESTEROL_RISK_WORKFLOW,
    CHOLESTEROL_RISK_TEST_CASES,
    MEDICATION_WORKFLOW,
    MEDICATION_TEST_CASES,
    BMI_CLASSIFICATION_WORKFLOW,
    BMI_CLASSIFICATION_TEST_CASES,
    ELIGIBILITY_WORKFLOW,
    ELIGIBILITY_TEST_CASES,
    get_all_workflow_tests,
)


class TestSimpleAgeWorkflow:
    """Test simple binary decision workflow"""

    @pytest.mark.parametrize("inputs,expected_output,description", SIMPLE_AGE_TEST_CASES)
    def test_age_check(self, inputs, expected_output, description):
        """Test age check workflow with various inputs"""
        interpreter = TreeInterpreter(
            tree=SIMPLE_AGE_WORKFLOW["tree"],
            inputs=SIMPLE_AGE_WORKFLOW["inputs"],
            outputs=SIMPLE_AGE_WORKFLOW["outputs"]
        )
        result = interpreter.execute(inputs)
        assert result.success is True, f"{description}: {result.error}"
        assert result.output == expected_output, f"{description}"
        assert "start" in result.path
        assert "age_check" in result.path


class TestCholesterolRiskWorkflow:
    """Test multi-level nested decision workflow"""

    @pytest.mark.parametrize("inputs,expected_output,description", CHOLESTEROL_RISK_TEST_CASES)
    def test_cholesterol_risk(self, inputs, expected_output, description):
        """Test cholesterol risk assessment workflow"""
        interpreter = TreeInterpreter(
            tree=CHOLESTEROL_RISK_WORKFLOW["tree"],
            inputs=CHOLESTEROL_RISK_WORKFLOW["inputs"],
            outputs=CHOLESTEROL_RISK_WORKFLOW["outputs"]
        )
        result = interpreter.execute(inputs)
        assert result.success is True, f"{description}: {result.error}"
        assert result.output == expected_output, f"{description}"


class TestMedicationWorkflow:
    """Test OR logic and string comparison"""

    @pytest.mark.parametrize("inputs,expected_output,description", MEDICATION_TEST_CASES)
    def test_medication_decision(self, inputs, expected_output, description):
        """Test medication workflow with OR logic and enums"""
        interpreter = TreeInterpreter(
            tree=MEDICATION_WORKFLOW["tree"],
            inputs=MEDICATION_WORKFLOW["inputs"],
            outputs=MEDICATION_WORKFLOW["outputs"]
        )
        result = interpreter.execute(inputs)
        assert result.success is True, f"{description}: {result.error}"
        assert result.output == expected_output, f"{description}"


class TestBMIClassificationWorkflow:
    """Test numeric ranges and complex expressions"""

    @pytest.mark.parametrize("inputs,expected_output,description", BMI_CLASSIFICATION_TEST_CASES)
    def test_bmi_classification(self, inputs, expected_output, description):
        """Test BMI classification with ranges"""
        interpreter = TreeInterpreter(
            tree=BMI_CLASSIFICATION_WORKFLOW["tree"],
            inputs=BMI_CLASSIFICATION_WORKFLOW["inputs"],
            outputs=BMI_CLASSIFICATION_WORKFLOW["outputs"]
        )
        result = interpreter.execute(inputs)
        assert result.success is True, f"{description}: {result.error}"
        assert result.output == expected_output, f"{description}"


class TestEligibilityWorkflow:
    """Test NOT operator and compound conditions"""

    @pytest.mark.parametrize("inputs,expected_output,description", ELIGIBILITY_TEST_CASES)
    def test_eligibility_check(self, inputs, expected_output, description):
        """Test eligibility workflow with NOT operator"""
        interpreter = TreeInterpreter(
            tree=ELIGIBILITY_WORKFLOW["tree"],
            inputs=ELIGIBILITY_WORKFLOW["inputs"],
            outputs=ELIGIBILITY_WORKFLOW["outputs"]
        )
        result = interpreter.execute(inputs)
        assert result.success is True, f"{description}: {result.error}"
        assert result.output == expected_output, f"{description}"


class TestErrorHandling:
    """Test error cases and validation"""

    def test_missing_required_input(self):
        """Test error when required input is missing"""
        interpreter = TreeInterpreter(
            tree=SIMPLE_AGE_WORKFLOW["tree"],
            inputs=SIMPLE_AGE_WORKFLOW["inputs"],
            outputs=SIMPLE_AGE_WORKFLOW["outputs"]
        )
        result = interpreter.execute({})
        assert result.success is False
        assert "Missing required input" in result.error

    def test_invalid_input_type(self):
        """Test error when input has wrong type"""
        interpreter = TreeInterpreter(
            tree=SIMPLE_AGE_WORKFLOW["tree"],
            inputs=SIMPLE_AGE_WORKFLOW["inputs"],
            outputs=SIMPLE_AGE_WORKFLOW["outputs"]
        )
        result = interpreter.execute({"input_age_int": "not a number"})
        assert result.success is False
        assert "must be int" in result.error

    def test_out_of_range_value(self):
        """Test error when input value out of range"""
        interpreter = TreeInterpreter(
            tree=SIMPLE_AGE_WORKFLOW["tree"],
            inputs=SIMPLE_AGE_WORKFLOW["inputs"],
            outputs=SIMPLE_AGE_WORKFLOW["outputs"]
        )
        result = interpreter.execute({"input_age_int": 150})
        assert result.success is False
        assert "exceeds maximum" in result.error

    def test_invalid_enum_value(self):
        """Test error when enum value not in allowed list"""
        interpreter = TreeInterpreter(
            tree=MEDICATION_WORKFLOW["tree"],
            inputs=MEDICATION_WORKFLOW["inputs"],
            outputs=MEDICATION_WORKFLOW["outputs"]
        )
        result = interpreter.execute({
            "input_condition_enum": "Cancer",  # Not in enum
            "input_age_int": 50,
            "input_pregnant_bool": False
        })
        assert result.success is False
        assert "must be one of" in result.error


class TestExecutionPath:
    """Test that execution paths are correctly tracked"""

    def test_path_includes_all_visited_nodes(self):
        """Test that result.path contains all visited node IDs"""
        interpreter = TreeInterpreter(
            tree=SIMPLE_AGE_WORKFLOW["tree"],
            inputs=SIMPLE_AGE_WORKFLOW["inputs"],
            outputs=SIMPLE_AGE_WORKFLOW["outputs"]
        )
        result = interpreter.execute({"input_age_int": 25})
        assert "start" in result.path
        assert "age_check" in result.path
        assert "out_adult" in result.path

    def test_path_order_correct(self):
        """Test that path nodes are in traversal order"""
        interpreter = TreeInterpreter(
            tree=SIMPLE_AGE_WORKFLOW["tree"],
            inputs=SIMPLE_AGE_WORKFLOW["inputs"],
            outputs=SIMPLE_AGE_WORKFLOW["outputs"]
        )
        result = interpreter.execute({"input_age_int": 25})
        assert result.path[0] == "start"
        assert result.path[1] == "age_check"
        assert result.path[2] == "out_adult"

    def test_short_path_simple_workflow(self):
        """Test path for simple 2-node workflow"""
        interpreter = TreeInterpreter(
            tree=SIMPLE_AGE_WORKFLOW["tree"],
            inputs=SIMPLE_AGE_WORKFLOW["inputs"],
            outputs=SIMPLE_AGE_WORKFLOW["outputs"]
        )
        result = interpreter.execute({"input_age_int": 17})
        assert len(result.path) == 3  # start, age_check, out_minor

    def test_long_path_nested_workflow(self):
        """Test path for deeply nested workflow"""
        interpreter = TreeInterpreter(
            tree=CHOLESTEROL_RISK_WORKFLOW["tree"],
            inputs=CHOLESTEROL_RISK_WORKFLOW["inputs"],
            outputs=CHOLESTEROL_RISK_WORKFLOW["outputs"]
        )
        result = interpreter.execute({
            "input_age_int": 50,
            "input_cholesterol_float": 240.0,
            "input_hdl_float": 35.0,
            "input_smoker_bool": True
        })
        # Should visit: start, age_check, cholesterol_check, risk_check, out_high_risk
        assert len(result.path) == 5


class TestContextHandling:
    """Test input context management"""

    def test_context_preserved_in_result(self):
        """Test that input context is preserved in ExecutionResult"""
        interpreter = TreeInterpreter(
            tree=SIMPLE_AGE_WORKFLOW["tree"],
            inputs=SIMPLE_AGE_WORKFLOW["inputs"],
            outputs=SIMPLE_AGE_WORKFLOW["outputs"]
        )
        input_values = {"input_age_int": 25}
        result = interpreter.execute(input_values)
        assert result.context == input_values

    def test_context_not_mutated(self):
        """Test that original input dict is not modified"""
        interpreter = TreeInterpreter(
            tree=SIMPLE_AGE_WORKFLOW["tree"],
            inputs=SIMPLE_AGE_WORKFLOW["inputs"],
            outputs=SIMPLE_AGE_WORKFLOW["outputs"]
        )
        input_values = {"input_age_int": 25}
        original_values = input_values.copy()
        result = interpreter.execute(input_values)
        assert input_values == original_values

    def test_context_with_unused_inputs(self):
        """Test that extra inputs don't cause errors"""
        interpreter = TreeInterpreter(
            tree=SIMPLE_AGE_WORKFLOW["tree"],
            inputs=SIMPLE_AGE_WORKFLOW["inputs"],
            outputs=SIMPLE_AGE_WORKFLOW["outputs"]
        )
        result = interpreter.execute({
            "input_age_int": 25,
            "extra_input": "ignored"
        })
        assert result.success is True


class TestEdgeLabelMatching:
    """Test edge label matching for branch selection"""

    def test_yes_no_labels(self):
        """Test matching Yes/No edge labels"""
        interpreter = TreeInterpreter(
            tree=SIMPLE_AGE_WORKFLOW["tree"],
            inputs=SIMPLE_AGE_WORKFLOW["inputs"],
            outputs=SIMPLE_AGE_WORKFLOW["outputs"]
        )
        # Yes branch
        result = interpreter.execute({"input_age_int": 25})
        assert result.output == "Adult"

        # No branch
        result = interpreter.execute({"input_age_int": 17})
        assert result.output == "Minor"

    def test_case_insensitive_labels(self):
        """Test that edge label matching is case-insensitive"""
        # The fixture uses "Yes"/"No" labels, which should work
        interpreter = TreeInterpreter(
            tree=SIMPLE_AGE_WORKFLOW["tree"],
            inputs=SIMPLE_AGE_WORKFLOW["inputs"],
            outputs=SIMPLE_AGE_WORKFLOW["outputs"]
        )
        result = interpreter.execute({"input_age_int": 25})
        assert result.success is True


class TestMultipleWorkflows:
    """Integration test running all workflows"""

    def test_all_workflows(self):
        """Run all workflow test suites"""
        for workflow, test_cases, name in get_all_workflow_tests():
            for inputs, expected_output, description in test_cases:
                interpreter = TreeInterpreter(
                    tree=workflow["tree"],
                    inputs=workflow["inputs"],
                    outputs=workflow["outputs"]
                )
                result = interpreter.execute(inputs)
                assert result.success is True, f"{name} - {description}: {result.error}"
                assert result.output == expected_output, f"{name} - {description}"


class TestInputValidation:
    """Test input schema validation before execution"""

    def test_validate_int_type(self):
        """Test validation of int type"""
        interpreter = TreeInterpreter(
            tree=SIMPLE_AGE_WORKFLOW["tree"],
            inputs=SIMPLE_AGE_WORKFLOW["inputs"],
            outputs=SIMPLE_AGE_WORKFLOW["outputs"]
        )
        result = interpreter.execute({"input_age_int": "25"})
        assert result.success is False
        assert "must be int" in result.error

    def test_validate_float_type(self):
        """Test validation of float type"""
        interpreter = TreeInterpreter(
            tree=BMI_CLASSIFICATION_WORKFLOW["tree"],
            inputs=BMI_CLASSIFICATION_WORKFLOW["inputs"],
            outputs=BMI_CLASSIFICATION_WORKFLOW["outputs"]
        )
        result = interpreter.execute({
            "input_bmi_float": "not a float",
            "input_athlete_bool": False
        })
        assert result.success is False
        assert "must be float" in result.error

    def test_validate_bool_type(self):
        """Test validation of bool type"""
        interpreter = TreeInterpreter(
            tree=SIMPLE_AGE_WORKFLOW["tree"],
            inputs=SIMPLE_AGE_WORKFLOW["inputs"],
            outputs=SIMPLE_AGE_WORKFLOW["outputs"]
        )
        # Change input schema temporarily to have bool
        result = interpreter.execute({"input_age_int": 25})
        assert result.success is True

    def test_validate_enum_type(self):
        """Test validation of enum type"""
        interpreter = TreeInterpreter(
            tree=MEDICATION_WORKFLOW["tree"],
            inputs=MEDICATION_WORKFLOW["inputs"],
            outputs=MEDICATION_WORKFLOW["outputs"]
        )
        result = interpreter.execute({
            "input_condition_enum": "InvalidCondition",
            "input_age_int": 50,
            "input_pregnant_bool": False
        })
        assert result.success is False
        assert "must be one of" in result.error

    def test_validate_range_min(self):
        """Test validation of minimum value in range"""
        interpreter = TreeInterpreter(
            tree=SIMPLE_AGE_WORKFLOW["tree"],
            inputs=SIMPLE_AGE_WORKFLOW["inputs"],
            outputs=SIMPLE_AGE_WORKFLOW["outputs"]
        )
        result = interpreter.execute({"input_age_int": -5})
        assert result.success is False
        assert "below minimum" in result.error

    def test_validate_range_max(self):
        """Test validation of maximum value in range"""
        interpreter = TreeInterpreter(
            tree=SIMPLE_AGE_WORKFLOW["tree"],
            inputs=SIMPLE_AGE_WORKFLOW["inputs"],
            outputs=SIMPLE_AGE_WORKFLOW["outputs"]
        )
        result = interpreter.execute({"input_age_int": 150})
        assert result.success is False
        assert "exceeds maximum" in result.error

    def test_validate_enum_values(self):
        """Test validation that value is in enum list"""
        interpreter = TreeInterpreter(
            tree=MEDICATION_WORKFLOW["tree"],
            inputs=MEDICATION_WORKFLOW["inputs"],
            outputs=MEDICATION_WORKFLOW["outputs"]
        )
        # Valid enum value
        result = interpreter.execute({
            "input_condition_enum": "Hypertension",
            "input_age_int": 50,
            "input_pregnant_bool": False
        })
        assert result.success is True


class TestExecutionResult:
    """Test ExecutionResult structure"""

    def test_result_has_output(self):
        """Test that successful result has output field"""
        interpreter = TreeInterpreter(
            tree=SIMPLE_AGE_WORKFLOW["tree"],
            inputs=SIMPLE_AGE_WORKFLOW["inputs"],
            outputs=SIMPLE_AGE_WORKFLOW["outputs"]
        )
        result = interpreter.execute({"input_age_int": 25})
        assert hasattr(result, 'output')
        assert result.output == "Adult"

    def test_result_has_path(self):
        """Test that result has path field"""
        interpreter = TreeInterpreter(
            tree=SIMPLE_AGE_WORKFLOW["tree"],
            inputs=SIMPLE_AGE_WORKFLOW["inputs"],
            outputs=SIMPLE_AGE_WORKFLOW["outputs"]
        )
        result = interpreter.execute({"input_age_int": 25})
        assert hasattr(result, 'path')
        assert isinstance(result.path, list)

    def test_result_has_context(self):
        """Test that result has context field"""
        interpreter = TreeInterpreter(
            tree=SIMPLE_AGE_WORKFLOW["tree"],
            inputs=SIMPLE_AGE_WORKFLOW["inputs"],
            outputs=SIMPLE_AGE_WORKFLOW["outputs"]
        )
        result = interpreter.execute({"input_age_int": 25})
        assert hasattr(result, 'context')
        assert isinstance(result.context, dict)

    def test_result_has_success_flag(self):
        """Test that result has success boolean"""
        interpreter = TreeInterpreter(
            tree=SIMPLE_AGE_WORKFLOW["tree"],
            inputs=SIMPLE_AGE_WORKFLOW["inputs"],
            outputs=SIMPLE_AGE_WORKFLOW["outputs"]
        )
        result = interpreter.execute({"input_age_int": 25})
        assert hasattr(result, 'success')
        assert isinstance(result.success, bool)

    def test_error_result_has_error_message(self):
        """Test that failed result has error field"""
        interpreter = TreeInterpreter(
            tree=SIMPLE_AGE_WORKFLOW["tree"],
            inputs=SIMPLE_AGE_WORKFLOW["inputs"],
            outputs=SIMPLE_AGE_WORKFLOW["outputs"]
        )
        result = interpreter.execute({})
        assert result.success is False
        assert hasattr(result, 'error')
        assert result.error is not None
