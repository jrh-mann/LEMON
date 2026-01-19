"""Expression evaluator: expression tree → boolean result

Evaluates parsed expressions with a context (variable bindings).
"""

from typing import Dict, Any
from .types import Expr, BinaryOp, UnaryOp, Variable, Literal


class EvaluationError(Exception):
    """Raised when evaluation fails"""
    pass


def evaluate(expr: Expr, context: Dict[str, Any]) -> Any:
    """Evaluate expression tree with given context

    Args:
        expr: Expression tree (from parser)
        context: Variable bindings (e.g., {"input_age_int": 25, "input_smoker_bool": True})

    Returns:
        Evaluation result (usually boolean for conditions)

    Raises:
        EvaluationError: If variable not found or type error occurs

    Examples:
        >>> from .parser import parse_condition
        >>> expr = parse_condition("Age >= 18")
        >>> evaluate(expr, {"Age": 25})
        True
        >>> evaluate(expr, {"Age": 17})
        False
    """
    if isinstance(expr, Literal):
        return expr.value

    elif isinstance(expr, Variable):
        if expr.name not in context:
            raise EvaluationError(f"Variable '{expr.name}' not found in context")
        return context[expr.name]

    elif isinstance(expr, UnaryOp):
        return evaluate_unary_op(expr, context)

    elif isinstance(expr, BinaryOp):
        return evaluate_binary_op(expr, context)

    else:
        raise EvaluationError(f"Unknown expression type: {type(expr)}")


def evaluate_unary_op(expr: UnaryOp, context: Dict[str, Any]) -> Any:
    """Evaluate unary operation

    Args:
        expr: UnaryOp node
        context: Variable bindings

    Returns:
        Result of operation
    """
    operand = evaluate(expr.operand, context)

    if expr.operator == "NOT":
        return not operand
    else:
        raise EvaluationError(f"Unknown unary operator: {expr.operator}")


def evaluate_binary_op(expr: BinaryOp, context: Dict[str, Any]) -> Any:
    """Evaluate binary operation

    Args:
        expr: BinaryOp node
        context: Variable bindings

    Returns:
        Result of operation
    """
    # Logical operators: short-circuit evaluation
    if expr.operator == "AND":
        left = evaluate(expr.left, context)
        if not left:
            return False
        return bool(evaluate(expr.right, context))

    elif expr.operator == "OR":
        left = evaluate(expr.left, context)
        if left:
            return True
        return bool(evaluate(expr.right, context))

    # Comparison operators: evaluate both sides
    left = evaluate(expr.left, context)
    right = evaluate(expr.right, context)

    if expr.operator == "==":
        return left == right

    elif expr.operator == "!=":
        return left != right

    elif expr.operator == ">":
        return compare_values(left, right, ">")

    elif expr.operator == "<":
        return compare_values(left, right, "<")

    elif expr.operator == ">=":
        return compare_values(left, right, ">=")

    elif expr.operator == "<=":
        return compare_values(left, right, "<=")

    else:
        raise EvaluationError(f"Unknown binary operator: {expr.operator}")


def compare_values(left: Any, right: Any, operator: str) -> bool:
    """Compare two values with type coercion

    Args:
        left: Left operand
        right: Right operand
        operator: Comparison operator (>, <, >=, <=)

    Returns:
        Comparison result

    Raises:
        EvaluationError: If types are incompatible for comparison
    """
    # Type coercion for numeric comparisons
    # Allow int/float mixing
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if operator == ">":
            return left > right
        elif operator == "<":
            return left < right
        elif operator == ">=":
            return left >= right
        elif operator == "<=":
            return left <= right

    # String comparison (lexicographic)
    elif isinstance(left, str) and isinstance(right, str):
        if operator == ">":
            return left > right
        elif operator == "<":
            return left < right
        elif operator == ">=":
            return left >= right
        elif operator == "<=":
            return left <= right

    # Boolean comparison (treat as 0/1)
    elif isinstance(left, bool) and isinstance(right, bool):
        if operator == ">":
            return left > right
        elif operator == "<":
            return left < right
        elif operator == ">=":
            return left >= right
        elif operator == "<=":
            return left <= right

    else:
        raise EvaluationError(
            f"Cannot compare {type(left).__name__} and {type(right).__name__} "
            f"with operator '{operator}'"
        )
