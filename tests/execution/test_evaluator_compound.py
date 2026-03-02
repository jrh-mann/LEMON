"""Tests for compound (AND/OR) condition evaluation.

Compound conditions combine multiple simple conditions with a logical operator:
- {"operator": "and", "conditions": [simple1, simple2, ...]} → all must be true
- {"operator": "or", "conditions": [simple1, simple2, ...]} → any must be true

One level deep only — sub-conditions cannot themselves be compound.
"""

import pytest
from src.backend.execution.evaluator import (
    evaluate_condition,
    is_compound_condition,
    EvaluationError,
)


class TestIsCompoundCondition:
    """Test the is_compound_condition() detection helper."""

    def test_simple_condition_returns_false(self):
        assert is_compound_condition({"input_id": "a1c", "comparator": "gt", "value": 58}) is False

    def test_compound_and_returns_true(self):
        cond = {
            "operator": "and",
            "conditions": [
                {"input_id": "a", "comparator": "is_true"},
                {"input_id": "b", "comparator": "gt", "value": 5},
            ],
        }
        assert is_compound_condition(cond) is True

    def test_compound_or_returns_true(self):
        cond = {
            "operator": "or",
            "conditions": [
                {"input_id": "a", "comparator": "is_true"},
                {"input_id": "b", "comparator": "gt", "value": 5},
            ],
        }
        assert is_compound_condition(cond) is True

    def test_non_dict_returns_false(self):
        assert is_compound_condition("not a dict") is False

    def test_empty_dict_returns_false(self):
        assert is_compound_condition({}) is False


class TestCompoundAnd:
    """Test AND compound conditions — all sub-conditions must be true."""

    def test_and_all_true(self):
        """AND with all sub-conditions true → True."""
        cond = {
            "operator": "and",
            "conditions": [
                {"input_id": "symptoms", "comparator": "is_true"},
                {"input_id": "a1c", "comparator": "gt", "value": 58},
            ],
        }
        ctx = {"symptoms": True, "a1c": 70}
        assert evaluate_condition(cond, ctx) is True

    def test_and_one_false(self):
        """AND with one sub-condition false → False."""
        cond = {
            "operator": "and",
            "conditions": [
                {"input_id": "symptoms", "comparator": "is_true"},
                {"input_id": "a1c", "comparator": "gt", "value": 58},
            ],
        }
        ctx = {"symptoms": True, "a1c": 50}
        assert evaluate_condition(cond, ctx) is False

    def test_and_all_false(self):
        """AND with all sub-conditions false → False."""
        cond = {
            "operator": "and",
            "conditions": [
                {"input_id": "symptoms", "comparator": "is_true"},
                {"input_id": "a1c", "comparator": "gt", "value": 58},
            ],
        }
        ctx = {"symptoms": False, "a1c": 50}
        assert evaluate_condition(cond, ctx) is False

    def test_and_three_conditions_all_true(self):
        """AND with three sub-conditions, all true → True."""
        cond = {
            "operator": "and",
            "conditions": [
                {"input_id": "a", "comparator": "gt", "value": 0},
                {"input_id": "b", "comparator": "gt", "value": 0},
                {"input_id": "c", "comparator": "gt", "value": 0},
            ],
        }
        ctx = {"a": 1, "b": 2, "c": 3}
        assert evaluate_condition(cond, ctx) is True

    def test_and_three_conditions_one_false(self):
        """AND with three sub-conditions, middle false → False."""
        cond = {
            "operator": "and",
            "conditions": [
                {"input_id": "a", "comparator": "gt", "value": 0},
                {"input_id": "b", "comparator": "gt", "value": 0},
                {"input_id": "c", "comparator": "gt", "value": 0},
            ],
        }
        ctx = {"a": 1, "b": -1, "c": 3}
        assert evaluate_condition(cond, ctx) is False


class TestCompoundOr:
    """Test OR compound conditions — any sub-condition must be true."""

    def test_or_all_true(self):
        """OR with all sub-conditions true → True."""
        cond = {
            "operator": "or",
            "conditions": [
                {"input_id": "cvd_known", "comparator": "is_true"},
                {"input_id": "cvd_at_risk", "comparator": "is_true"},
            ],
        }
        ctx = {"cvd_known": True, "cvd_at_risk": True}
        assert evaluate_condition(cond, ctx) is True

    def test_or_one_true(self):
        """OR with one sub-condition true → True."""
        cond = {
            "operator": "or",
            "conditions": [
                {"input_id": "cvd_known", "comparator": "is_true"},
                {"input_id": "cvd_at_risk", "comparator": "is_true"},
            ],
        }
        ctx = {"cvd_known": False, "cvd_at_risk": True}
        assert evaluate_condition(cond, ctx) is True

    def test_or_all_false(self):
        """OR with all sub-conditions false → False."""
        cond = {
            "operator": "or",
            "conditions": [
                {"input_id": "cvd_known", "comparator": "is_true"},
                {"input_id": "cvd_at_risk", "comparator": "is_true"},
            ],
        }
        ctx = {"cvd_known": False, "cvd_at_risk": False}
        assert evaluate_condition(cond, ctx) is False


class TestCompoundMixedTypes:
    """Test compound conditions with different comparator types."""

    def test_and_bool_and_numeric(self):
        """AND combining boolean and numeric comparators."""
        cond = {
            "operator": "and",
            "conditions": [
                {"input_id": "diabetic", "comparator": "is_true"},
                {"input_id": "age", "comparator": "gte", "value": 40},
            ],
        }
        ctx = {"diabetic": True, "age": 55}
        assert evaluate_condition(cond, ctx) is True

    def test_or_string_and_enum(self):
        """OR combining string and enum comparators."""
        cond = {
            "operator": "or",
            "conditions": [
                {"input_id": "name", "comparator": "str_contains", "value": "admin"},
                {"input_id": "role", "comparator": "enum_eq", "value": "superuser"},
            ],
        }
        ctx = {"name": "regular_user", "role": "superuser"}
        assert evaluate_condition(cond, ctx) is True


class TestCompoundErrorHandling:
    """Test error handling for invalid compound conditions."""

    def test_missing_input_in_sub_condition(self):
        """Sub-condition referencing missing input raises EvaluationError."""
        cond = {
            "operator": "and",
            "conditions": [
                {"input_id": "exists", "comparator": "is_true"},
                {"input_id": "missing", "comparator": "gt", "value": 5},
            ],
        }
        ctx = {"exists": True}
        with pytest.raises(EvaluationError, match="not found in execution context"):
            evaluate_condition(cond, ctx)

    def test_invalid_operator_value(self):
        """Compound condition with invalid operator raises EvaluationError."""
        cond = {
            "operator": "xor",
            "conditions": [
                {"input_id": "a", "comparator": "is_true"},
                {"input_id": "b", "comparator": "is_true"},
            ],
        }
        ctx = {"a": True, "b": True}
        with pytest.raises(EvaluationError, match="Unknown compound operator"):

            evaluate_condition(cond, ctx)

    def test_empty_conditions_array(self):
        """Compound condition with empty conditions array raises EvaluationError."""
        cond = {"operator": "and", "conditions": []}
        with pytest.raises(EvaluationError, match="at least 2"):
            evaluate_condition(cond, {})

    def test_single_condition_array(self):
        """Compound condition with only 1 sub-condition raises EvaluationError."""
        cond = {
            "operator": "and",
            "conditions": [{"input_id": "a", "comparator": "is_true"}],
        }
        with pytest.raises(EvaluationError, match="at least 2"):
            evaluate_condition(cond, {"a": True})

    def test_conditions_not_a_list(self):
        """Compound condition where conditions is not a list raises EvaluationError."""
        cond = {"operator": "and", "conditions": "not a list"}
        with pytest.raises(EvaluationError, match="must be a list"):
            evaluate_condition(cond, {})
