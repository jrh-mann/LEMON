"""Tests for expression evaluator (expression tree → boolean result)"""

import pytest
from src.backend.execution.parser import parse_condition
from src.backend.execution.evaluator import evaluate, EvaluationError


class TestExpressionEvaluator:
    """Test evaluation of parsed expressions with context"""

    def test_simple_gte_true(self):
        """Test: Age >= 18 with Age=25 → True"""
        expr = parse_condition("Age >= 18")
        result = evaluate(expr, {"Age": 25})
        assert result is True

    def test_simple_gte_false(self):
        """Test: Age >= 18 with Age=17 → False"""
        expr = parse_condition("Age >= 18")
        result = evaluate(expr, {"Age": 17})
        assert result is False

    def test_simple_gte_boundary(self):
        """Test: Age >= 18 with Age=18 → True"""
        expr = parse_condition("Age >= 18")
        result = evaluate(expr, {"Age": 18})
        assert result is True

    def test_simple_lt_true(self):
        """Test: BMI < 18.5 with BMI=17.0 → True"""
        expr = parse_condition("BMI < 18.5")
        result = evaluate(expr, {"BMI": 17.0})
        assert result is True

    def test_simple_lt_false(self):
        """Test: BMI < 18.5 with BMI=20.0 → False"""
        expr = parse_condition("BMI < 18.5")
        result = evaluate(expr, {"BMI": 20.0})
        assert result is False

    def test_equality_bool_true(self):
        """Test: Smoker == True with Smoker=True → True"""
        expr = parse_condition("Smoker == True")
        result = evaluate(expr, {"Smoker": True})
        assert result is True

    def test_equality_bool_false(self):
        """Test: Smoker == True with Smoker=False → False"""
        expr = parse_condition("Smoker == True")
        result = evaluate(expr, {"Smoker": False})
        assert result is False

    def test_equality_string_true(self):
        """Test: Condition == 'Hypertension' with Condition='Hypertension' → True"""
        expr = parse_condition("Condition == 'Hypertension'")
        result = evaluate(expr, {"Condition": "Hypertension"})
        assert result is True

    def test_equality_string_false(self):
        """Test: Condition == 'Hypertension' with Condition='Diabetes' → False"""
        expr = parse_condition("Condition == 'Hypertension'")
        result = evaluate(expr, {"Condition": "Diabetes"})
        assert result is False

    def test_and_both_true(self):
        """Test: Age >= 18 AND Citizen == True with both true → True"""
        expr = parse_condition("Age >= 18 AND Citizen == True")
        result = evaluate(expr, {"Age": 25, "Citizen": True})
        assert result is True

    def test_and_one_false(self):
        """Test: Age >= 18 AND Citizen == True with Age=17 → False"""
        expr = parse_condition("Age >= 18 AND Citizen == True")
        result = evaluate(expr, {"Age": 17, "Citizen": True})
        assert result is False

    def test_and_both_false(self):
        """Test: Age >= 18 AND Citizen == True with both false → False"""
        expr = parse_condition("Age >= 18 AND Citizen == True")
        result = evaluate(expr, {"Age": 17, "Citizen": False})
        assert result is False

    def test_or_both_true(self):
        """Test: A == 1 OR B == 2 with both true → True"""
        expr = parse_condition("A == 1 OR B == 2")
        result = evaluate(expr, {"A": 1, "B": 2})
        assert result is True

    def test_or_one_true(self):
        """Test: A == 1 OR B == 2 with A=1, B=3 → True"""
        expr = parse_condition("A == 1 OR B == 2")
        result = evaluate(expr, {"A": 1, "B": 3})
        assert result is True

    def test_or_both_false(self):
        """Test: A == 1 OR B == 2 with both false → False"""
        expr = parse_condition("A == 1 OR B == 2")
        result = evaluate(expr, {"A": 99, "B": 99})
        assert result is False

    def test_not_operator_true(self):
        """Test: NOT Convicted == True with Convicted=False → True"""
        expr = parse_condition("NOT Convicted == True")
        result = evaluate(expr, {"Convicted": False})
        assert result is True

    def test_not_operator_false(self):
        """Test: NOT Convicted == True with Convicted=True → False"""
        expr = parse_condition("NOT Convicted == True")
        result = evaluate(expr, {"Convicted": True})
        assert result is False

    def test_compound_and_expression(self):
        """Test: HDL < 40 AND Smoker == True"""
        expr = parse_condition("HDL < 40 AND Smoker == True")

        # Both true
        result = evaluate(expr, {"HDL": 35.0, "Smoker": True})
        assert result is True

        # First false
        result = evaluate(expr, {"HDL": 50.0, "Smoker": True})
        assert result is False

        # Second false
        result = evaluate(expr, {"HDL": 35.0, "Smoker": False})
        assert result is False

    def test_compound_or_expression(self):
        """Test: Condition == 'Hypertension' OR Condition == 'Heart Disease'"""
        expr = parse_condition("Condition == 'Hypertension' OR Condition == 'Heart Disease'")

        result = evaluate(expr, {"Condition": "Hypertension"})
        assert result is True

        result = evaluate(expr, {"Condition": "Heart Disease"})
        assert result is True

        result = evaluate(expr, {"Condition": "Diabetes"})
        assert result is False

    def test_range_check(self):
        """Test: BMI >= 18.5 AND BMI < 25"""
        expr = parse_condition("BMI >= 18.5 AND BMI < 25")

        # In range
        result = evaluate(expr, {"BMI": 22.0})
        assert result is True

        # Lower boundary (inclusive)
        result = evaluate(expr, {"BMI": 18.5})
        assert result is True

        # Upper boundary (exclusive)
        result = evaluate(expr, {"BMI": 25.0})
        assert result is False

        # Below range
        result = evaluate(expr, {"BMI": 17.0})
        assert result is False

        # Above range
        result = evaluate(expr, {"BMI": 30.0})
        assert result is False

    def test_float_comparison(self):
        """Test: Cholesterol >= 200.0 with float values"""
        expr = parse_condition("Cholesterol >= 200.0")

        result = evaluate(expr, {"Cholesterol": 240.5})
        assert result is True

        result = evaluate(expr, {"Cholesterol": 180.3})
        assert result is False

        result = evaluate(expr, {"Cholesterol": 200.0})
        assert result is True

    def test_not_equals_true(self):
        """Test: Status != 'inactive' with Status='active' → True"""
        expr = parse_condition("Status != 'inactive'")
        result = evaluate(expr, {"Status": "active"})
        assert result is True

    def test_not_equals_false(self):
        """Test: Status != 'inactive' with Status='inactive' → False"""
        expr = parse_condition("Status != 'inactive'")
        result = evaluate(expr, {"Status": "inactive"})
        assert result is False

    def test_missing_variable_error(self):
        """Test error when variable not in context"""
        expr = parse_condition("Age >= 18")
        with pytest.raises(EvaluationError, match="Variable 'Age' not found"):
            evaluate(expr, {})

    def test_type_coercion_int_to_float(self):
        """Test: BMI < 18.5 with BMI=18 (int) should work"""
        expr = parse_condition("BMI < 18.5")
        result = evaluate(expr, {"BMI": 18})  # int value
        assert result is True

    def test_nested_parentheses(self):
        """Test: (Age >= 18 AND Age <= 65) OR Athlete == True"""
        expr = parse_condition("(Age >= 18 AND Age <= 65) OR Athlete == True")

        # In age range, not athlete
        result = evaluate(expr, {"Age": 30, "Athlete": False})
        assert result is True

        # Out of age range, but athlete
        result = evaluate(expr, {"Age": 70, "Athlete": True})
        assert result is True

        # Out of age range, not athlete
        result = evaluate(expr, {"Age": 70, "Athlete": False})
        assert result is False

    def test_operator_precedence(self):
        """Test: A OR B AND C (AND binds tighter than OR)"""
        expr = parse_condition("A == 1 OR B == 2 AND C == 3")

        # Should parse as: A == 1 OR (B == 2 AND C == 3)
        # A true, others don't matter
        result = evaluate(expr, {"A": 1, "B": 99, "C": 99})
        assert result is True

        # A false, B and C both true
        result = evaluate(expr, {"A": 99, "B": 2, "C": 3})
        assert result is True

        # A false, B true but C false
        result = evaluate(expr, {"A": 99, "B": 2, "C": 99})
        assert result is False

        # All false
        result = evaluate(expr, {"A": 99, "B": 99, "C": 99})
        assert result is False

    def test_short_circuit_and(self):
        """Test that AND short-circuits (doesn't evaluate right if left is false)"""
        expr = parse_condition("A == 1 AND B == 2")

        # First condition false - should short-circuit without needing B
        result = evaluate(expr, {"A": 99})  # B not in context
        assert result is False

    def test_short_circuit_or(self):
        """Test that OR short-circuits (doesn't evaluate right if left is true)"""
        expr = parse_condition("A == 1 OR B == 2")

        # First condition true - should short-circuit without needing B
        result = evaluate(expr, {"A": 1})  # B not in context
        assert result is True

    def test_gt_operator(self):
        """Test > operator"""
        expr = parse_condition("Age > 18")

        result = evaluate(expr, {"Age": 19})
        assert result is True

        result = evaluate(expr, {"Age": 18})
        assert result is False

        result = evaluate(expr, {"Age": 17})
        assert result is False

    def test_lte_operator(self):
        """Test <= operator"""
        expr = parse_condition("Age <= 65")

        result = evaluate(expr, {"Age": 60})
        assert result is True

        result = evaluate(expr, {"Age": 65})
        assert result is True

        result = evaluate(expr, {"Age": 70})
        assert result is False

    def test_complex_expression(self):
        """Test complex real-world expression"""
        expr = parse_condition("Age >= 40 AND Cholesterol >= 200 AND (HDL < 40 OR Smoker == True)")

        # All conditions met via HDL
        result = evaluate(expr, {"Age": 50, "Cholesterol": 240, "HDL": 35, "Smoker": False})
        assert result is True

        # All conditions met via Smoker
        result = evaluate(expr, {"Age": 50, "Cholesterol": 240, "HDL": 50, "Smoker": True})
        assert result is True

        # Age too low
        result = evaluate(expr, {"Age": 35, "Cholesterol": 240, "HDL": 35, "Smoker": False})
        assert result is False

        # Cholesterol too low
        result = evaluate(expr, {"Age": 50, "Cholesterol": 180, "HDL": 35, "Smoker": False})
        assert result is False

        # Neither HDL nor Smoker condition met
        result = evaluate(expr, {"Age": 50, "Cholesterol": 240, "HDL": 50, "Smoker": False})
        assert result is False

    def test_string_equality_case_sensitive(self):
        """Test that string equality is case-sensitive"""
        expr = parse_condition("Status == 'Active'")

        result = evaluate(expr, {"Status": "Active"})
        assert result is True

        result = evaluate(expr, {"Status": "active"})
        assert result is False

        result = evaluate(expr, {"Status": "ACTIVE"})
        assert result is False

    def test_numeric_equality(self):
        """Test numeric equality"""
        expr = parse_condition("Count == 10")

        result = evaluate(expr, {"Count": 10})
        assert result is True

        result = evaluate(expr, {"Count": 10.0})
        assert result is True

        result = evaluate(expr, {"Count": 9})
        assert result is False
