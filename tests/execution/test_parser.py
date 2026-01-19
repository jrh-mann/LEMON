"""Tests for condition parser (string → expression tree)"""

import pytest
from src.backend.execution.parser import parse_condition, LexerError, ParseError
from src.backend.execution.types import BinaryOp, UnaryOp, Variable, Literal


class TestConditionParser:
    """Test parsing of condition strings into expression trees"""

    def test_simple_comparison_gte(self):
        """Test: Age >= 18"""
        expr = parse_condition("Age >= 18")
        assert isinstance(expr, BinaryOp)
        assert expr.operator == ">="
        assert isinstance(expr.left, Variable)
        assert expr.left.name == "Age"
        assert isinstance(expr.right, Literal)
        assert expr.right.value == 18

    def test_simple_comparison_lt(self):
        """Test: BMI < 18.5"""
        expr = parse_condition("BMI < 18.5")
        assert isinstance(expr, BinaryOp)
        assert expr.operator == "<"
        assert isinstance(expr.left, Variable)
        assert expr.left.name == "BMI"
        assert isinstance(expr.right, Literal)
        assert expr.right.value == 18.5

    def test_simple_equality_bool(self):
        """Test: Smoker == True"""
        expr = parse_condition("Smoker == True")
        assert isinstance(expr, BinaryOp)
        assert expr.operator == "=="
        assert isinstance(expr.left, Variable)
        assert expr.left.name == "Smoker"
        assert isinstance(expr.right, Literal)
        assert expr.right.value is True

    def test_simple_equality_string(self):
        """Test: Condition == 'Hypertension'"""
        expr = parse_condition("Condition == 'Hypertension'")
        assert isinstance(expr, BinaryOp)
        assert expr.operator == "=="
        assert isinstance(expr.left, Variable)
        assert expr.left.name == "Condition"
        assert isinstance(expr.right, Literal)
        assert expr.right.value == "Hypertension"

    def test_and_operator(self):
        """Test: Age >= 18 AND Age <= 65"""
        expr = parse_condition("Age >= 18 AND Age <= 65")
        assert isinstance(expr, BinaryOp)
        assert expr.operator == "AND"

        # Left side: Age >= 18
        assert isinstance(expr.left, BinaryOp)
        assert expr.left.operator == ">="
        assert expr.left.left.name == "Age"
        assert expr.left.right.value == 18

        # Right side: Age <= 65
        assert isinstance(expr.right, BinaryOp)
        assert expr.right.operator == "<="
        assert expr.right.left.name == "Age"
        assert expr.right.right.value == 65

    def test_or_operator(self):
        """Test: Condition == 'Hypertension' OR Condition == 'Heart Disease'"""
        expr = parse_condition("Condition == 'Hypertension' OR Condition == 'Heart Disease'")
        assert isinstance(expr, BinaryOp)
        assert expr.operator == "OR"

        # Left side
        assert isinstance(expr.left, BinaryOp)
        assert expr.left.operator == "=="
        assert expr.left.left.name == "Condition"
        assert expr.left.right.value == "Hypertension"

        # Right side
        assert isinstance(expr.right, BinaryOp)
        assert expr.right.operator == "=="
        assert expr.right.left.name == "Condition"
        assert expr.right.right.value == "Heart Disease"

    def test_not_operator(self):
        """Test: NOT Convicted == True"""
        expr = parse_condition("NOT Convicted == True")
        assert isinstance(expr, UnaryOp)
        assert expr.operator == "NOT"

        # Operand: Convicted == True
        assert isinstance(expr.operand, BinaryOp)
        assert expr.operand.operator == "=="
        assert expr.operand.left.name == "Convicted"
        assert expr.operand.right.value is True

    def test_complex_nested(self):
        """Test: HDL < 40 AND Smoker == True"""
        expr = parse_condition("HDL < 40 AND Smoker == True")
        assert isinstance(expr, BinaryOp)
        assert expr.operator == "AND"

        # Left: HDL < 40
        assert expr.left.operator == "<"
        assert expr.left.left.name == "HDL"
        assert expr.left.right.value == 40

        # Right: Smoker == True
        assert expr.right.operator == "=="
        assert expr.right.left.name == "Smoker"
        assert expr.right.right.value is True

    def test_triple_and(self):
        """Test: BMI >= 18.5 AND BMI < 25"""
        expr = parse_condition("BMI >= 18.5 AND BMI < 25")
        assert isinstance(expr, BinaryOp)
        assert expr.operator == "AND"
        assert expr.left.operator == ">="
        assert expr.right.operator == "<"

    def test_whitespace_handling(self):
        """Test that extra whitespace is handled correctly"""
        expr1 = parse_condition("Age>=18")
        expr2 = parse_condition("Age   >=   18")
        expr3 = parse_condition("  Age >= 18  ")

        # All should parse to same structure
        for expr in [expr1, expr2, expr3]:
            assert isinstance(expr, BinaryOp)
            assert expr.operator == ">="
            assert expr.left.name == "Age"
            assert expr.right.value == 18

    def test_case_insensitivity_operators(self):
        """Test: age >= 18 and smoker == true (lowercase operators)"""
        expr = parse_condition("age >= 18 and smoker == true")
        assert isinstance(expr, BinaryOp)
        assert expr.operator == "AND"

        # Variables preserve case
        assert expr.left.left.name == "age"
        assert expr.right.left.name == "smoker"

        # Boolean keywords are normalized
        assert expr.right.right.value is True

    def test_invalid_syntax_missing_operand(self):
        """Test error handling for: Age >="""
        with pytest.raises(ParseError):
            parse_condition("Age >=")

    def test_invalid_syntax_unknown_operator(self):
        """Test error handling for: Age ~= 18"""
        with pytest.raises(LexerError):
            parse_condition("Age ~= 18")

    def test_float_literal(self):
        """Test: Cholesterol >= 200.5"""
        expr = parse_condition("Cholesterol >= 200.5")
        assert isinstance(expr, BinaryOp)
        assert expr.right.value == 200.5
        assert isinstance(expr.right.value, float)

    def test_string_with_quotes(self):
        """Test: Status == 'active' or Status == \"active\""""
        expr1 = parse_condition("Status == 'active'")
        expr2 = parse_condition('Status == "active"')

        # Both should work
        assert expr1.right.value == "active"
        assert expr2.right.value == "active"

    def test_boolean_literal_true(self):
        """Test: Pregnant == True"""
        expr = parse_condition("Pregnant == True")
        assert expr.right.value is True
        assert isinstance(expr.right.value, bool)

    def test_boolean_literal_false(self):
        """Test: Smoker == False"""
        expr = parse_condition("Smoker == False")
        assert expr.right.value is False
        assert isinstance(expr.right.value, bool)

    def test_parentheses(self):
        """Test: (Age >= 18 AND Age <= 65) OR Athlete == True"""
        expr = parse_condition("(Age >= 18 AND Age <= 65) OR Athlete == True")
        assert isinstance(expr, BinaryOp)
        assert expr.operator == "OR"

        # Left side should be the AND expression (parentheses grouped it)
        assert isinstance(expr.left, BinaryOp)
        assert expr.left.operator == "AND"

        # Right side
        assert isinstance(expr.right, BinaryOp)
        assert expr.right.left.name == "Athlete"

    def test_not_equals(self):
        """Test: Status != 'inactive'"""
        expr = parse_condition("Status != 'inactive'")
        assert isinstance(expr, BinaryOp)
        assert expr.operator == "!="
        assert expr.left.name == "Status"
        assert expr.right.value == "inactive"

    def test_chained_or(self):
        """Test: A == 1 OR B == 2 OR C == 3"""
        expr = parse_condition("A == 1 OR B == 2 OR C == 3")

        # Should be left-associative: (A == 1 OR B == 2) OR C == 3
        assert isinstance(expr, BinaryOp)
        assert expr.operator == "OR"

        # Left side: A == 1 OR B == 2
        assert isinstance(expr.left, BinaryOp)
        assert expr.left.operator == "OR"

        # Right side: C == 3
        assert isinstance(expr.right, BinaryOp)
        assert expr.right.left.name == "C"

    def test_mixed_and_or(self):
        """Test: Age >= 18 AND (Citizen == True OR Resident == True)"""
        expr = parse_condition("Age >= 18 AND (Citizen == True OR Resident == True)")
        assert isinstance(expr, BinaryOp)
        assert expr.operator == "AND"

        # Left: Age >= 18
        assert expr.left.operator == ">="

        # Right: (Citizen == True OR Resident == True)
        assert isinstance(expr.right, BinaryOp)
        assert expr.right.operator == "OR"

    def test_all_comparison_operators(self):
        """Test all comparison operators"""
        operators = [
            ("Age > 18", ">"),
            ("Age < 18", "<"),
            ("Age >= 18", ">="),
            ("Age <= 18", "<="),
            ("Age == 18", "=="),
            ("Age != 18", "!="),
        ]

        for condition_str, expected_op in operators:
            expr = parse_condition(condition_str)
            assert isinstance(expr, BinaryOp)
            assert expr.operator == expected_op

    def test_empty_string_error(self):
        """Test error handling for empty string"""
        with pytest.raises(ParseError):
            parse_condition("")

    def test_whitespace_only_error(self):
        """Test error handling for whitespace only"""
        with pytest.raises(ParseError):
            parse_condition("   ")

    def test_unclosed_parenthesis(self):
        """Test error handling for unclosed parenthesis"""
        with pytest.raises(ParseError):
            parse_condition("(Age >= 18")

    def test_unclosed_string(self):
        """Test error handling for unclosed string"""
        with pytest.raises(LexerError):
            parse_condition("Status == 'active")

    def test_variable_with_underscores(self):
        """Test: input_age_int >= 18"""
        expr = parse_condition("input_age_int >= 18")
        assert expr.left.name == "input_age_int"

    def test_operator_precedence_and_before_or(self):
        """Test: A OR B AND C should parse as A OR (B AND C)"""
        expr = parse_condition("A == 1 OR B == 2 AND C == 3")

        # Should be: A == 1 OR (B == 2 AND C == 3)
        assert isinstance(expr, BinaryOp)
        assert expr.operator == "OR"

        # Right side should be AND
        assert isinstance(expr.right, BinaryOp)
        assert expr.right.operator == "AND"
