"""Tests for condition evaluation.

Tests cover:
- Basic comparisons
- Boolean operators
- Membership testing
- Security (rejecting dangerous operations)
- Variable validation
"""

import pytest

from lemon.execution.conditions import ConditionEvaluator
from lemon.core.exceptions import InvalidConditionError, UnknownVariableError


@pytest.fixture
def evaluator():
    return ConditionEvaluator()


# -----------------------------------------------------------------------------
# Basic Comparisons
# -----------------------------------------------------------------------------


class TestBasicComparisons:
    """Tests for basic comparison operators."""

    def test_greater_than(self, evaluator):
        assert evaluator.evaluate("age > 18", {"age": 25}) is True
        assert evaluator.evaluate("age > 18", {"age": 18}) is False
        assert evaluator.evaluate("age > 18", {"age": 10}) is False

    def test_greater_than_or_equal(self, evaluator):
        assert evaluator.evaluate("age >= 18", {"age": 25}) is True
        assert evaluator.evaluate("age >= 18", {"age": 18}) is True
        assert evaluator.evaluate("age >= 18", {"age": 10}) is False

    def test_less_than(self, evaluator):
        assert evaluator.evaluate("x < 5", {"x": 3}) is True
        assert evaluator.evaluate("x < 5", {"x": 5}) is False
        assert evaluator.evaluate("x < 5", {"x": 10}) is False

    def test_less_than_or_equal(self, evaluator):
        assert evaluator.evaluate("x <= 5", {"x": 3}) is True
        assert evaluator.evaluate("x <= 5", {"x": 5}) is True
        assert evaluator.evaluate("x <= 5", {"x": 10}) is False

    def test_equality(self, evaluator):
        assert evaluator.evaluate("x == 5", {"x": 5}) is True
        assert evaluator.evaluate("x == 5", {"x": 3}) is False

    def test_inequality(self, evaluator):
        assert evaluator.evaluate("x != 5", {"x": 3}) is True
        assert evaluator.evaluate("x != 5", {"x": 5}) is False

    def test_chained_comparison(self, evaluator):
        assert evaluator.evaluate("10 < age < 30", {"age": 20}) is True
        assert evaluator.evaluate("10 < age < 30", {"age": 5}) is False
        assert evaluator.evaluate("10 < age < 30", {"age": 35}) is False

    def test_float_comparison(self, evaluator):
        assert evaluator.evaluate("egfr < 45.5", {"egfr": 40.0}) is True
        assert evaluator.evaluate("egfr < 45.5", {"egfr": 50.0}) is False

    def test_string_comparison(self, evaluator):
        assert evaluator.evaluate("status == 'active'", {"status": "active"}) is True
        assert evaluator.evaluate('status == "active"', {"status": "active"}) is True
        assert evaluator.evaluate("status == 'active'", {"status": "inactive"}) is False


# -----------------------------------------------------------------------------
# Boolean Operators
# -----------------------------------------------------------------------------


class TestBooleanOperators:
    """Tests for boolean operators."""

    def test_and_operator(self, evaluator):
        assert evaluator.evaluate("x > 5 and y < 10", {"x": 6, "y": 8}) is True
        assert evaluator.evaluate("x > 5 and y < 10", {"x": 4, "y": 8}) is False
        assert evaluator.evaluate("x > 5 and y < 10", {"x": 6, "y": 12}) is False

    def test_or_operator(self, evaluator):
        assert evaluator.evaluate("x > 5 or y < 10", {"x": 6, "y": 8}) is True
        assert evaluator.evaluate("x > 5 or y < 10", {"x": 4, "y": 8}) is True
        assert evaluator.evaluate("x > 5 or y < 10", {"x": 4, "y": 12}) is False

    def test_not_operator(self, evaluator):
        assert evaluator.evaluate("not x", {"x": False}) is True
        assert evaluator.evaluate("not x", {"x": True}) is False
        assert evaluator.evaluate("not (x > 5)", {"x": 3}) is True

    def test_complex_boolean(self, evaluator):
        condition = "(age >= 18 and status == 'active') or admin"
        assert evaluator.evaluate(condition, {"age": 25, "status": "active", "admin": False}) is True
        assert evaluator.evaluate(condition, {"age": 15, "status": "active", "admin": False}) is False
        assert evaluator.evaluate(condition, {"age": 15, "status": "inactive", "admin": True}) is True


# -----------------------------------------------------------------------------
# Membership Testing
# -----------------------------------------------------------------------------


class TestMembershipTesting:
    """Tests for 'in' and 'not in' operators."""

    def test_in_list(self, evaluator):
        assert evaluator.evaluate("status in ['active', 'pending']", {"status": "active"}) is True
        assert evaluator.evaluate("status in ['active', 'pending']", {"status": "inactive"}) is False

    def test_not_in_list(self, evaluator):
        assert evaluator.evaluate("status not in ['banned', 'deleted']", {"status": "active"}) is True
        assert evaluator.evaluate("status not in ['banned', 'deleted']", {"status": "banned"}) is False

    def test_in_with_numbers(self, evaluator):
        assert evaluator.evaluate("x in [1, 2, 3]", {"x": 2}) is True
        assert evaluator.evaluate("x in [1, 2, 3]", {"x": 5}) is False


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------


class TestConstants:
    """Tests for boolean constants and None."""

    def test_true_false(self, evaluator):
        assert evaluator.evaluate("x == True", {"x": True}) is True
        assert evaluator.evaluate("x == False", {"x": False}) is True
        assert evaluator.evaluate("x", {"x": True}) is True
        assert evaluator.evaluate("x", {"x": False}) is False

    def test_none(self, evaluator):
        assert evaluator.evaluate("x == None", {"x": None}) is True
        assert evaluator.evaluate("x != None", {"x": "something"}) is True


# -----------------------------------------------------------------------------
# Security Tests
# -----------------------------------------------------------------------------


class TestSecurity:
    """Tests for rejecting dangerous operations."""

    def test_rejects_function_calls(self, evaluator):
        with pytest.raises(InvalidConditionError) as exc_info:
            evaluator.evaluate("len(x) > 5", {"x": "hello"})
        assert "Function calls" in str(exc_info.value) or "Unsupported" in str(exc_info.value)

    def test_rejects_attribute_access(self, evaluator):
        with pytest.raises(InvalidConditionError) as exc_info:
            evaluator.evaluate("x.__class__", {"x": "hello"})
        assert "Attribute access" in str(exc_info.value) or "Unsupported" in str(exc_info.value)

    def test_rejects_subscript(self, evaluator):
        with pytest.raises(InvalidConditionError) as exc_info:
            evaluator.evaluate("x[0] == 'a'", {"x": "abc"})
        assert "Subscript" in str(exc_info.value) or "Unsupported" in str(exc_info.value)

    def test_rejects_import(self, evaluator):
        with pytest.raises(InvalidConditionError):
            evaluator.evaluate("__import__('os')", {})

    def test_rejects_arithmetic(self, evaluator):
        with pytest.raises(InvalidConditionError) as exc_info:
            evaluator.evaluate("x + y > 10", {"x": 5, "y": 6})
        assert "Arithmetic" in str(exc_info.value) or "Unsupported" in str(exc_info.value)


# -----------------------------------------------------------------------------
# Variable Handling
# -----------------------------------------------------------------------------


class TestVariableHandling:
    """Tests for variable reference handling."""

    def test_unknown_variable_raises(self, evaluator):
        with pytest.raises(UnknownVariableError) as exc_info:
            evaluator.evaluate("unknown > 5", {"x": 10})
        assert "unknown" in str(exc_info.value)

    def test_get_referenced_variables(self, evaluator):
        vars = evaluator.get_referenced_variables("x > 5 and y < 10")
        assert vars == {"x", "y"}

    def test_get_referenced_variables_complex(self, evaluator):
        vars = evaluator.get_referenced_variables("(a >= b and c != d) or e in [1, 2]")
        assert vars == {"a", "b", "c", "d", "e"}


# -----------------------------------------------------------------------------
# Validation
# -----------------------------------------------------------------------------


class TestValidation:
    """Tests for condition validation."""

    def test_validate_valid_condition(self, evaluator):
        errors = evaluator.validate("age >= 18", ["age"])
        assert errors == []

    def test_validate_syntax_error(self, evaluator):
        errors = evaluator.validate("age >=", ["age"])
        assert len(errors) > 0
        assert "Syntax" in errors[0]

    def test_validate_unknown_variable(self, evaluator):
        errors = evaluator.validate("unknown > 5", ["age"])
        assert len(errors) > 0
        assert "Unknown variables" in errors[0]

    def test_validate_disallowed_operation(self, evaluator):
        errors = evaluator.validate("len(x) > 5", ["x"])
        assert len(errors) > 0
        assert "Function" in errors[0] or "call" in errors[0].lower()


# -----------------------------------------------------------------------------
# Edge Cases
# -----------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_context(self, evaluator):
        # Condition with only literals
        assert evaluator.evaluate("5 > 3", {}) is True

    def test_negative_numbers(self, evaluator):
        assert evaluator.evaluate("x > -5", {"x": 0}) is True
        assert evaluator.evaluate("x > -5", {"x": -10}) is False

    def test_boolean_variable_in_condition(self, evaluator):
        assert evaluator.evaluate("is_admin", {"is_admin": True}) is True
        assert evaluator.evaluate("is_admin", {"is_admin": False}) is False

    def test_whitespace_handling(self, evaluator):
        assert evaluator.evaluate("  age   >=   18  ", {"age": 20}) is True
