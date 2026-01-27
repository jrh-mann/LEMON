"""Tests for structured condition evaluator (DecisionCondition → boolean result)

Tests the new structured condition evaluator that uses comparators like:
- Numeric: eq, neq, lt, lte, gt, gte, within_range
- Boolean: is_true, is_false
- String: str_eq, str_neq, str_contains, str_starts_with, str_ends_with
- Date: date_eq, date_before, date_after, date_between
- Enum: enum_eq, enum_neq
"""

import pytest
from datetime import date
from src.backend.execution.evaluator import evaluate_condition, EvaluationError


class TestNumericComparators:
    """Test numeric comparators (eq, neq, lt, lte, gt, gte, within_range)"""

    def test_eq_true(self):
        """Test: input_age_int == 25 with value 25 → True"""
        condition = {"input_id": "input_age_int", "comparator": "eq", "value": 25}
        result = evaluate_condition(condition, {"input_age_int": 25})
        assert result is True

    def test_eq_false(self):
        """Test: input_age_int == 25 with value 30 → False"""
        condition = {"input_id": "input_age_int", "comparator": "eq", "value": 25}
        result = evaluate_condition(condition, {"input_age_int": 30})
        assert result is False

    def test_neq_true(self):
        """Test: input_age_int != 25 with value 30 → True"""
        condition = {"input_id": "input_age_int", "comparator": "neq", "value": 25}
        result = evaluate_condition(condition, {"input_age_int": 30})
        assert result is True

    def test_neq_false(self):
        """Test: input_age_int != 25 with value 25 → False"""
        condition = {"input_id": "input_age_int", "comparator": "neq", "value": 25}
        result = evaluate_condition(condition, {"input_age_int": 25})
        assert result is False

    def test_lt_true(self):
        """Test: input_bmi_float < 18.5 with value 17.0 → True"""
        condition = {"input_id": "input_bmi_float", "comparator": "lt", "value": 18.5}
        result = evaluate_condition(condition, {"input_bmi_float": 17.0})
        assert result is True

    def test_lt_false(self):
        """Test: input_bmi_float < 18.5 with value 20.0 → False"""
        condition = {"input_id": "input_bmi_float", "comparator": "lt", "value": 18.5}
        result = evaluate_condition(condition, {"input_bmi_float": 20.0})
        assert result is False

    def test_lt_boundary(self):
        """Test: input_bmi_float < 18.5 with value 18.5 → False"""
        condition = {"input_id": "input_bmi_float", "comparator": "lt", "value": 18.5}
        result = evaluate_condition(condition, {"input_bmi_float": 18.5})
        assert result is False

    def test_lte_true_less(self):
        """Test: input_age_int <= 65 with value 60 → True"""
        condition = {"input_id": "input_age_int", "comparator": "lte", "value": 65}
        result = evaluate_condition(condition, {"input_age_int": 60})
        assert result is True

    def test_lte_true_equal(self):
        """Test: input_age_int <= 65 with value 65 → True"""
        condition = {"input_id": "input_age_int", "comparator": "lte", "value": 65}
        result = evaluate_condition(condition, {"input_age_int": 65})
        assert result is True

    def test_lte_false(self):
        """Test: input_age_int <= 65 with value 70 → False"""
        condition = {"input_id": "input_age_int", "comparator": "lte", "value": 65}
        result = evaluate_condition(condition, {"input_age_int": 70})
        assert result is False

    def test_gt_true(self):
        """Test: input_age_int > 18 with value 25 → True"""
        condition = {"input_id": "input_age_int", "comparator": "gt", "value": 18}
        result = evaluate_condition(condition, {"input_age_int": 25})
        assert result is True

    def test_gt_false(self):
        """Test: input_age_int > 18 with value 17 → False"""
        condition = {"input_id": "input_age_int", "comparator": "gt", "value": 18}
        result = evaluate_condition(condition, {"input_age_int": 17})
        assert result is False

    def test_gt_boundary(self):
        """Test: input_age_int > 18 with value 18 → False"""
        condition = {"input_id": "input_age_int", "comparator": "gt", "value": 18}
        result = evaluate_condition(condition, {"input_age_int": 18})
        assert result is False

    def test_gte_true_greater(self):
        """Test: input_age_int >= 18 with value 25 → True"""
        condition = {"input_id": "input_age_int", "comparator": "gte", "value": 18}
        result = evaluate_condition(condition, {"input_age_int": 25})
        assert result is True

    def test_gte_true_equal(self):
        """Test: input_age_int >= 18 with value 18 → True"""
        condition = {"input_id": "input_age_int", "comparator": "gte", "value": 18}
        result = evaluate_condition(condition, {"input_age_int": 18})
        assert result is True

    def test_gte_false(self):
        """Test: input_age_int >= 18 with value 17 → False"""
        condition = {"input_id": "input_age_int", "comparator": "gte", "value": 18}
        result = evaluate_condition(condition, {"input_age_int": 17})
        assert result is False

    def test_within_range_inside(self):
        """Test: input_bmi_float within [18.5, 25] with value 22 → True"""
        condition = {"input_id": "input_bmi_float", "comparator": "within_range", "value": 18.5, "value2": 25.0}
        result = evaluate_condition(condition, {"input_bmi_float": 22.0})
        assert result is True

    def test_within_range_lower_boundary(self):
        """Test: input_bmi_float within [18.5, 25] with value 18.5 → True"""
        condition = {"input_id": "input_bmi_float", "comparator": "within_range", "value": 18.5, "value2": 25.0}
        result = evaluate_condition(condition, {"input_bmi_float": 18.5})
        assert result is True

    def test_within_range_upper_boundary(self):
        """Test: input_bmi_float within [18.5, 25] with value 25 → True"""
        condition = {"input_id": "input_bmi_float", "comparator": "within_range", "value": 18.5, "value2": 25.0}
        result = evaluate_condition(condition, {"input_bmi_float": 25.0})
        assert result is True

    def test_within_range_below(self):
        """Test: input_bmi_float within [18.5, 25] with value 17 → False"""
        condition = {"input_id": "input_bmi_float", "comparator": "within_range", "value": 18.5, "value2": 25.0}
        result = evaluate_condition(condition, {"input_bmi_float": 17.0})
        assert result is False

    def test_within_range_above(self):
        """Test: input_bmi_float within [18.5, 25] with value 30 → False"""
        condition = {"input_id": "input_bmi_float", "comparator": "within_range", "value": 18.5, "value2": 25.0}
        result = evaluate_condition(condition, {"input_bmi_float": 30.0})
        assert result is False

    def test_int_float_coercion(self):
        """Test: float comparator works with int value"""
        condition = {"input_id": "input_bmi_float", "comparator": "lt", "value": 18.5}
        result = evaluate_condition(condition, {"input_bmi_float": 18})  # int value
        assert result is True


class TestBooleanComparators:
    """Test boolean comparators (is_true, is_false)"""

    def test_is_true_with_true(self):
        """Test: input_active_bool is_true with True → True"""
        condition = {"input_id": "input_active_bool", "comparator": "is_true", "value": True}
        result = evaluate_condition(condition, {"input_active_bool": True})
        assert result is True

    def test_is_true_with_false(self):
        """Test: input_active_bool is_true with False → False"""
        condition = {"input_id": "input_active_bool", "comparator": "is_true", "value": True}
        result = evaluate_condition(condition, {"input_active_bool": False})
        assert result is False

    def test_is_false_with_false(self):
        """Test: input_active_bool is_false with False → True"""
        condition = {"input_id": "input_active_bool", "comparator": "is_false", "value": False}
        result = evaluate_condition(condition, {"input_active_bool": False})
        assert result is True

    def test_is_false_with_true(self):
        """Test: input_active_bool is_false with True → False"""
        condition = {"input_id": "input_active_bool", "comparator": "is_false", "value": False}
        result = evaluate_condition(condition, {"input_active_bool": True})
        assert result is False


class TestStringComparators:
    """Test string comparators (str_eq, str_neq, str_contains, str_starts_with, str_ends_with)"""

    def test_str_eq_same_case(self):
        """Test: input_name_string str_eq 'John' with 'John' → True"""
        condition = {"input_id": "input_name_string", "comparator": "str_eq", "value": "John"}
        result = evaluate_condition(condition, {"input_name_string": "John"})
        assert result is True

    def test_str_eq_different_case(self):
        """Test: input_name_string str_eq 'john' with 'JOHN' → True (case-insensitive)"""
        condition = {"input_id": "input_name_string", "comparator": "str_eq", "value": "john"}
        result = evaluate_condition(condition, {"input_name_string": "JOHN"})
        assert result is True

    def test_str_eq_different_value(self):
        """Test: input_name_string str_eq 'John' with 'Jane' → False"""
        condition = {"input_id": "input_name_string", "comparator": "str_eq", "value": "John"}
        result = evaluate_condition(condition, {"input_name_string": "Jane"})
        assert result is False

    def test_str_neq_different(self):
        """Test: input_name_string str_neq 'John' with 'Jane' → True"""
        condition = {"input_id": "input_name_string", "comparator": "str_neq", "value": "John"}
        result = evaluate_condition(condition, {"input_name_string": "Jane"})
        assert result is True

    def test_str_neq_same(self):
        """Test: input_name_string str_neq 'John' with 'john' → False (case-insensitive)"""
        condition = {"input_id": "input_name_string", "comparator": "str_neq", "value": "John"}
        result = evaluate_condition(condition, {"input_name_string": "john"})
        assert result is False

    def test_str_contains_found(self):
        """Test: input_email_string str_contains '@gmail.com' with 'user@gmail.com' → True"""
        condition = {"input_id": "input_email_string", "comparator": "str_contains", "value": "@gmail.com"}
        result = evaluate_condition(condition, {"input_email_string": "user@gmail.com"})
        assert result is True

    def test_str_contains_not_found(self):
        """Test: input_email_string str_contains '@gmail.com' with 'user@yahoo.com' → False"""
        condition = {"input_id": "input_email_string", "comparator": "str_contains", "value": "@gmail.com"}
        result = evaluate_condition(condition, {"input_email_string": "user@yahoo.com"})
        assert result is False

    def test_str_contains_case_insensitive(self):
        """Test: input_email_string str_contains '@GMAIL.COM' with 'user@gmail.com' → True"""
        condition = {"input_id": "input_email_string", "comparator": "str_contains", "value": "@GMAIL.COM"}
        result = evaluate_condition(condition, {"input_email_string": "user@gmail.com"})
        assert result is True

    def test_str_starts_with_true(self):
        """Test: input_code_string str_starts_with 'PRE' with 'PREFIX123' → True"""
        condition = {"input_id": "input_code_string", "comparator": "str_starts_with", "value": "PRE"}
        result = evaluate_condition(condition, {"input_code_string": "PREFIX123"})
        assert result is True

    def test_str_starts_with_false(self):
        """Test: input_code_string str_starts_with 'PRE' with 'NOTPRE123' → False"""
        condition = {"input_id": "input_code_string", "comparator": "str_starts_with", "value": "PRE"}
        result = evaluate_condition(condition, {"input_code_string": "NOTPRE123"})
        assert result is False

    def test_str_ends_with_true(self):
        """Test: input_file_string str_ends_with '.pdf' with 'report.pdf' → True"""
        condition = {"input_id": "input_file_string", "comparator": "str_ends_with", "value": ".pdf"}
        result = evaluate_condition(condition, {"input_file_string": "report.pdf"})
        assert result is True

    def test_str_ends_with_false(self):
        """Test: input_file_string str_ends_with '.pdf' with 'report.docx' → False"""
        condition = {"input_id": "input_file_string", "comparator": "str_ends_with", "value": ".pdf"}
        result = evaluate_condition(condition, {"input_file_string": "report.docx"})
        assert result is False


class TestDateComparators:
    """Test date comparators (date_eq, date_before, date_after, date_between)"""

    def test_date_eq_same(self):
        """Test: input_date_date date_eq '2024-01-15' with same date → True"""
        condition = {"input_id": "input_date_date", "comparator": "date_eq", "value": "2024-01-15"}
        result = evaluate_condition(condition, {"input_date_date": "2024-01-15"})
        assert result is True

    def test_date_eq_different(self):
        """Test: input_date_date date_eq '2024-01-15' with different date → False"""
        condition = {"input_id": "input_date_date", "comparator": "date_eq", "value": "2024-01-15"}
        result = evaluate_condition(condition, {"input_date_date": "2024-01-16"})
        assert result is False

    def test_date_eq_with_date_object(self):
        """Test: date_eq works with date object in context"""
        condition = {"input_id": "input_date_date", "comparator": "date_eq", "value": "2024-01-15"}
        result = evaluate_condition(condition, {"input_date_date": date(2024, 1, 15)})
        assert result is True

    def test_date_before_true(self):
        """Test: input_date_date date_before '2024-06-01' with '2024-01-15' → True"""
        condition = {"input_id": "input_date_date", "comparator": "date_before", "value": "2024-06-01"}
        result = evaluate_condition(condition, {"input_date_date": "2024-01-15"})
        assert result is True

    def test_date_before_false(self):
        """Test: input_date_date date_before '2024-01-01' with '2024-06-15' → False"""
        condition = {"input_id": "input_date_date", "comparator": "date_before", "value": "2024-01-01"}
        result = evaluate_condition(condition, {"input_date_date": "2024-06-15"})
        assert result is False

    def test_date_after_true(self):
        """Test: input_date_date date_after '2024-01-01' with '2024-06-15' → True"""
        condition = {"input_id": "input_date_date", "comparator": "date_after", "value": "2024-01-01"}
        result = evaluate_condition(condition, {"input_date_date": "2024-06-15"})
        assert result is True

    def test_date_after_false(self):
        """Test: input_date_date date_after '2024-06-01' with '2024-01-15' → False"""
        condition = {"input_id": "input_date_date", "comparator": "date_after", "value": "2024-06-01"}
        result = evaluate_condition(condition, {"input_date_date": "2024-01-15"})
        assert result is False

    def test_date_between_inside(self):
        """Test: input_date_date date_between ['2024-01-01', '2024-12-31'] with '2024-06-15' → True"""
        condition = {"input_id": "input_date_date", "comparator": "date_between", "value": "2024-01-01", "value2": "2024-12-31"}
        result = evaluate_condition(condition, {"input_date_date": "2024-06-15"})
        assert result is True

    def test_date_between_lower_boundary(self):
        """Test: input_date_date date_between with date at lower boundary → True"""
        condition = {"input_id": "input_date_date", "comparator": "date_between", "value": "2024-01-01", "value2": "2024-12-31"}
        result = evaluate_condition(condition, {"input_date_date": "2024-01-01"})
        assert result is True

    def test_date_between_outside(self):
        """Test: input_date_date date_between ['2024-01-01', '2024-12-31'] with '2025-06-15' → False"""
        condition = {"input_id": "input_date_date", "comparator": "date_between", "value": "2024-01-01", "value2": "2024-12-31"}
        result = evaluate_condition(condition, {"input_date_date": "2025-06-15"})
        assert result is False


class TestEnumComparators:
    """Test enum comparators (enum_eq, enum_neq)"""

    def test_enum_eq_same_case(self):
        """Test: input_tier_enum enum_eq 'Premium' with 'Premium' → True"""
        condition = {"input_id": "input_tier_enum", "comparator": "enum_eq", "value": "Premium"}
        result = evaluate_condition(condition, {"input_tier_enum": "Premium"})
        assert result is True

    def test_enum_eq_different_case(self):
        """Test: input_tier_enum enum_eq 'Premium' with 'premium' → True (case-insensitive)"""
        condition = {"input_id": "input_tier_enum", "comparator": "enum_eq", "value": "Premium"}
        result = evaluate_condition(condition, {"input_tier_enum": "premium"})
        assert result is True

    def test_enum_eq_different_value(self):
        """Test: input_tier_enum enum_eq 'Premium' with 'Basic' → False"""
        condition = {"input_id": "input_tier_enum", "comparator": "enum_eq", "value": "Premium"}
        result = evaluate_condition(condition, {"input_tier_enum": "Basic"})
        assert result is False

    def test_enum_neq_different(self):
        """Test: input_tier_enum enum_neq 'Premium' with 'Basic' → True"""
        condition = {"input_id": "input_tier_enum", "comparator": "enum_neq", "value": "Premium"}
        result = evaluate_condition(condition, {"input_tier_enum": "Basic"})
        assert result is True

    def test_enum_neq_same(self):
        """Test: input_tier_enum enum_neq 'Premium' with 'PREMIUM' → False (case-insensitive)"""
        condition = {"input_id": "input_tier_enum", "comparator": "enum_neq", "value": "Premium"}
        result = evaluate_condition(condition, {"input_tier_enum": "PREMIUM"})
        assert result is False


class TestErrorHandling:
    """Test error handling for invalid conditions"""

    def test_missing_input_id(self):
        """Test error when condition has no input_id"""
        condition = {"comparator": "eq", "value": 25}
        with pytest.raises(EvaluationError, match="missing 'input_id'"):
            evaluate_condition(condition, {"input_age_int": 25})

    def test_missing_comparator(self):
        """Test error when condition has no comparator"""
        condition = {"input_id": "input_age_int", "value": 25}
        with pytest.raises(EvaluationError, match="missing 'comparator'"):
            evaluate_condition(condition, {"input_age_int": 25})

    def test_unknown_comparator(self):
        """Test error when comparator is unknown"""
        condition = {"input_id": "input_age_int", "comparator": "invalid_op", "value": 25}
        with pytest.raises(EvaluationError, match="Unknown comparator"):
            evaluate_condition(condition, {"input_age_int": 25})

    def test_input_not_in_context(self):
        """Test error when input_id not found in context"""
        condition = {"input_id": "input_age_int", "comparator": "eq", "value": 25}
        with pytest.raises(EvaluationError, match="not found in execution context"):
            evaluate_condition(condition, {"input_other": 30})

    def test_invalid_condition_type(self):
        """Test error when condition is not a dict"""
        with pytest.raises(EvaluationError, match="must be a dict"):
            evaluate_condition("invalid", {"input_age_int": 25})

    def test_numeric_comparator_with_boolean(self):
        """Test error when using numeric comparator with boolean"""
        condition = {"input_id": "input_active_bool", "comparator": "gt", "value": 0}
        with pytest.raises(EvaluationError, match="boolean value"):
            evaluate_condition(condition, {"input_active_bool": True})

    def test_invalid_date_format(self):
        """Test error when date string is invalid"""
        condition = {"input_id": "input_date_date", "comparator": "date_eq", "value": "2024-01-15"}
        with pytest.raises(EvaluationError, match="Cannot parse date"):
            evaluate_condition(condition, {"input_date_date": "not-a-date"})
