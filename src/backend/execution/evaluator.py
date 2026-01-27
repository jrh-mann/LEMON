"""Structured condition evaluator for decision nodes.

Evaluates DecisionCondition objects against execution context.
Supports type-specific comparators for int, float, bool, string, date, and enum types.
"""

from typing import Dict, Any, Optional
from datetime import datetime, date


class EvaluationError(Exception):
    """Raised when condition evaluation fails."""
    pass


# ============ Valid Comparators by Type ============

NUMERIC_COMPARATORS = {'eq', 'neq', 'lt', 'lte', 'gt', 'gte', 'within_range'}
BOOLEAN_COMPARATORS = {'is_true', 'is_false'}
STRING_COMPARATORS = {'str_eq', 'str_neq', 'str_contains', 'str_starts_with', 'str_ends_with'}
DATE_COMPARATORS = {'date_eq', 'date_before', 'date_after', 'date_between'}
ENUM_COMPARATORS = {'enum_eq', 'enum_neq'}

ALL_COMPARATORS = (
    NUMERIC_COMPARATORS |
    BOOLEAN_COMPARATORS |
    STRING_COMPARATORS |
    DATE_COMPARATORS |
    ENUM_COMPARATORS
)


def evaluate_condition(condition: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """Evaluate a structured DecisionCondition against execution context.

    Args:
        condition: DecisionCondition dict with keys:
            - input_id: str - The workflow input ID to compare (e.g., "input_age_int")
            - comparator: str - The comparison operator (e.g., "gte", "is_true", "str_contains")
            - value: Any - The value to compare against
            - value2: Any (optional) - Second value for range comparisons
        context: Execution context mapping input IDs to their values.

    Returns:
        bool - True if condition is satisfied, False otherwise.

    Raises:
        EvaluationError: If input not found, comparator unknown, or type mismatch.

    Examples:
        >>> evaluate_condition(
        ...     {"input_id": "input_age_int", "comparator": "gte", "value": 18},
        ...     {"input_age_int": 25}
        ... )
        True
        >>> evaluate_condition(
        ...     {"input_id": "input_name_string", "comparator": "str_contains", "value": "john"},
        ...     {"input_name_string": "John Doe"}
        ... )
        True
    """
    # Validate condition structure
    if not isinstance(condition, dict):
        raise EvaluationError(f"Condition must be a dict, got {type(condition).__name__}")

    input_id = condition.get('input_id')
    comparator = condition.get('comparator')
    compare_value = condition.get('value')
    compare_value2 = condition.get('value2')

    if not input_id:
        raise EvaluationError("Condition missing 'input_id'")
    if not comparator:
        raise EvaluationError("Condition missing 'comparator'")
    if comparator not in ALL_COMPARATORS:
        raise EvaluationError(f"Unknown comparator: '{comparator}'")

    # Get actual value from context
    if input_id not in context:
        raise EvaluationError(f"Input '{input_id}' not found in execution context")

    actual_value = context[input_id]

    # Apply the comparator
    return _apply_comparator(actual_value, comparator, compare_value, compare_value2)


def _apply_comparator(
    actual: Any,
    comparator: str,
    value: Any,
    value2: Optional[Any] = None
) -> bool:
    """Apply a comparator to compare actual value against expected value(s).

    Args:
        actual: The actual value from the workflow input.
        comparator: The comparison operator.
        value: The expected value to compare against.
        value2: Second expected value (for range comparisons).

    Returns:
        bool - True if comparison succeeds.

    Raises:
        EvaluationError: If comparator is invalid or types don't match.
    """
    # ============ Numeric Comparators ============
    if comparator == 'eq':
        return actual == value

    if comparator == 'neq':
        return actual != value

    if comparator == 'lt':
        _ensure_numeric(actual, 'lt')
        _ensure_numeric(value, 'lt')
        return actual < value

    if comparator == 'lte':
        _ensure_numeric(actual, 'lte')
        _ensure_numeric(value, 'lte')
        return actual <= value

    if comparator == 'gt':
        _ensure_numeric(actual, 'gt')
        _ensure_numeric(value, 'gt')
        return actual > value

    if comparator == 'gte':
        _ensure_numeric(actual, 'gte')
        _ensure_numeric(value, 'gte')
        return actual >= value

    if comparator == 'within_range':
        _ensure_numeric(actual, 'within_range')
        _ensure_numeric(value, 'within_range')
        _ensure_numeric(value2, 'within_range')
        # Inclusive range: value <= actual <= value2
        return value <= actual <= value2

    # ============ Boolean Comparators ============
    if comparator == 'is_true':
        return actual is True

    if comparator == 'is_false':
        return actual is False

    # ============ String Comparators (case-insensitive) ============
    if comparator == 'str_eq':
        return str(actual).lower() == str(value).lower()

    if comparator == 'str_neq':
        return str(actual).lower() != str(value).lower()

    if comparator == 'str_contains':
        return str(value).lower() in str(actual).lower()

    if comparator == 'str_starts_with':
        return str(actual).lower().startswith(str(value).lower())

    if comparator == 'str_ends_with':
        return str(actual).lower().endswith(str(value).lower())

    # ============ Date Comparators ============
    if comparator == 'date_eq':
        actual_date = _parse_date(actual)
        compare_date = _parse_date(value)
        return actual_date == compare_date

    if comparator == 'date_before':
        actual_date = _parse_date(actual)
        compare_date = _parse_date(value)
        return actual_date < compare_date

    if comparator == 'date_after':
        actual_date = _parse_date(actual)
        compare_date = _parse_date(value)
        return actual_date > compare_date

    if comparator == 'date_between':
        actual_date = _parse_date(actual)
        start_date = _parse_date(value)
        end_date = _parse_date(value2)
        # Inclusive range: start <= actual <= end
        return start_date <= actual_date <= end_date

    # ============ Enum Comparators (case-insensitive string comparison) ============
    if comparator == 'enum_eq':
        return str(actual).lower() == str(value).lower()

    if comparator == 'enum_neq':
        return str(actual).lower() != str(value).lower()

    # Should never reach here if ALL_COMPARATORS is in sync
    raise EvaluationError(f"Unhandled comparator: '{comparator}'")


def _ensure_numeric(value: Any, comparator: str) -> None:
    """Ensure value is numeric (int or float, but not bool).

    Args:
        value: Value to check.
        comparator: Comparator name (for error message).

    Raises:
        EvaluationError: If value is not numeric.
    """
    # Note: bool is subclass of int in Python, so check bool first
    if isinstance(value, bool):
        raise EvaluationError(
            f"Cannot use '{comparator}' comparator with boolean value. "
            f"Use 'is_true' or 'is_false' instead."
        )
    if not isinstance(value, (int, float)):
        raise EvaluationError(
            f"'{comparator}' comparator requires numeric value, "
            f"got {type(value).__name__}: {value}"
        )


def _parse_date(value: Any) -> date:
    """Parse a date value from various formats.

    Accepts:
        - datetime.date object
        - datetime.datetime object (extracts date)
        - ISO format string "YYYY-MM-DD"
        - ISO format string with time "YYYY-MM-DDTHH:MM:SS..."

    Args:
        value: Value to parse as date.

    Returns:
        datetime.date object.

    Raises:
        EvaluationError: If value cannot be parsed as date.
    """
    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, str):
        try:
            # Try ISO format with time first
            if 'T' in value:
                return datetime.fromisoformat(value.replace('Z', '+00:00')).date()
            # Try date-only format
            return datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError:
            raise EvaluationError(
                f"Cannot parse date from string: '{value}'. "
                f"Expected ISO format 'YYYY-MM-DD'."
            )

    raise EvaluationError(
        f"Cannot parse date from {type(value).__name__}: {value}. "
        f"Expected date object or ISO format string."
    )
