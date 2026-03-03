"""Operator registry for calculation nodes.

Provides a registry of mathematical operators that can be used in calculation
nodes. Each operator has defined arity (number of operands) and an execute
function that performs the computation.

Operators are organized by arity:
- Unary (arity=1): Single operand operations like negate, abs, sqrt
- Binary (arity=2): Two operand operations like subtract, divide, power
- Variadic (arity>=2): Variable number of operands like add, multiply, min, max
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Union

# Type alias for numeric values - we use float internally for the unified 'number' type
Number = Union[int, float]


class OperatorError(Exception):
    """Exception raised when an operator execution fails.
    
    This is a runtime error that occurs when operator inputs are invalid
    (e.g., sqrt of negative number, division by zero). These errors are
    caught at runtime, not design-time.
    """
    
    def __init__(self, operator: str, message: str):
        self.operator = operator
        self.message = message
        super().__init__(f"Operator '{operator}' error: {message}")


@dataclass
class Operator:
    """Definition of a mathematical operator.
    
    Attributes:
        name: Internal identifier (e.g., "add", "sqrt")
        display_name: Human-readable name (e.g., "Add", "Square Root")
        symbol: Mathematical symbol if applicable (e.g., "+", "-", "sqrt")
        min_arity: Minimum number of operands required
        max_arity: Maximum number of operands allowed (None for unlimited)
        execute: Function that takes operands and returns result
        description: Explanation of what the operator does
    """
    name: str
    display_name: str
    symbol: str
    min_arity: int
    max_arity: Optional[int]  # None means unlimited (variadic)
    execute: Callable[[List[Number]], Number]
    description: str


# =============================================================================
# Operator Implementations
# =============================================================================

# -----------------------------------------------------------------------------
# Unary Operators (arity=1)
# -----------------------------------------------------------------------------

def _negate(operands: List[Number]) -> Number:
    """Negate: -x"""
    return -operands[0]


def _abs(operands: List[Number]) -> Number:
    """Absolute value: |x|"""
    return abs(operands[0])


def _sqrt(operands: List[Number]) -> Number:
    """Square root: sqrt(x). Raises error for negative input."""
    x = operands[0]
    if x < 0:
        raise OperatorError("sqrt", f"Cannot compute square root of negative number: {x}")
    return math.sqrt(x)


def _square(operands: List[Number]) -> Number:
    """Square: x^2"""
    return operands[0] ** 2


def _cube(operands: List[Number]) -> Number:
    """Cube: x^3"""
    return operands[0] ** 3


def _reciprocal(operands: List[Number]) -> Number:
    """Reciprocal: 1/x. Raises error for zero."""
    x = operands[0]
    if x == 0:
        raise OperatorError("reciprocal", "Cannot compute reciprocal of zero")
    return 1.0 / x


def _floor(operands: List[Number]) -> Number:
    """Floor: largest integer <= x"""
    return math.floor(operands[0])


def _ceil(operands: List[Number]) -> Number:
    """Ceiling: smallest integer >= x"""
    return math.ceil(operands[0])


def _round(operands: List[Number]) -> Number:
    """Round to nearest integer"""
    return round(operands[0])


def _sign(operands: List[Number]) -> Number:
    """Sign: -1, 0, or 1"""
    x = operands[0]
    if x > 0:
        return 1
    elif x < 0:
        return -1
    return 0


def _ln(operands: List[Number]) -> Number:
    """Natural logarithm: ln(x). Raises error for non-positive input."""
    x = operands[0]
    if x <= 0:
        raise OperatorError("ln", f"Cannot compute natural log of non-positive number: {x}")
    return math.log(x)


def _log10(operands: List[Number]) -> Number:
    """Base-10 logarithm: log10(x). Raises error for non-positive input."""
    x = operands[0]
    if x <= 0:
        raise OperatorError("log10", f"Cannot compute log10 of non-positive number: {x}")
    return math.log10(x)


def _exp(operands: List[Number]) -> Number:
    """Exponential: e^x"""
    return math.exp(operands[0])


def _sin(operands: List[Number]) -> Number:
    """Sine (radians)"""
    return math.sin(operands[0])


def _cos(operands: List[Number]) -> Number:
    """Cosine (radians)"""
    return math.cos(operands[0])


def _tan(operands: List[Number]) -> Number:
    """Tangent (radians)"""
    return math.tan(operands[0])


def _asin(operands: List[Number]) -> Number:
    """Arc sine: asin(x). Raises error if |x| > 1."""
    x = operands[0]
    if abs(x) > 1:
        raise OperatorError("asin", f"asin argument must be in [-1, 1], got: {x}")
    return math.asin(x)


def _acos(operands: List[Number]) -> Number:
    """Arc cosine: acos(x). Raises error if |x| > 1."""
    x = operands[0]
    if abs(x) > 1:
        raise OperatorError("acos", f"acos argument must be in [-1, 1], got: {x}")
    return math.acos(x)


def _atan(operands: List[Number]) -> Number:
    """Arc tangent: atan(x)"""
    return math.atan(operands[0])


def _degrees(operands: List[Number]) -> Number:
    """Convert radians to degrees"""
    return math.degrees(operands[0])


def _radians(operands: List[Number]) -> Number:
    """Convert degrees to radians"""
    return math.radians(operands[0])


# -----------------------------------------------------------------------------
# Binary Operators (arity=2)
# -----------------------------------------------------------------------------

def _subtract(operands: List[Number]) -> Number:
    """Subtract: a - b"""
    return operands[0] - operands[1]


def _divide(operands: List[Number]) -> Number:
    """Divide: a / b. Raises error for division by zero."""
    if operands[1] == 0:
        raise OperatorError("divide", "Division by zero")
    return operands[0] / operands[1]


def _floor_divide(operands: List[Number]) -> Number:
    """Floor division: a // b. Raises error for division by zero."""
    if operands[1] == 0:
        raise OperatorError("floor_divide", "Floor division by zero")
    return operands[0] // operands[1]


def _modulo(operands: List[Number]) -> Number:
    """Modulo: a % b. Raises error for modulo by zero."""
    if operands[1] == 0:
        raise OperatorError("modulo", "Modulo by zero")
    return operands[0] % operands[1]


def _power(operands: List[Number]) -> Number:
    """Power: a^b"""
    return operands[0] ** operands[1]


def _log(operands: List[Number]) -> Number:
    """Logarithm with custom base: log_b(a). Raises error for invalid inputs."""
    a, b = operands[0], operands[1]
    if a <= 0:
        raise OperatorError("log", f"Cannot compute log of non-positive number: {a}")
    if b <= 0 or b == 1:
        raise OperatorError("log", f"Log base must be positive and != 1, got: {b}")
    return math.log(a, b)


def _atan2(operands: List[Number]) -> Number:
    """Two-argument arc tangent: atan2(y, x)"""
    return math.atan2(operands[0], operands[1])


# -----------------------------------------------------------------------------
# Variadic Operators (arity>=2, unlimited max)
# -----------------------------------------------------------------------------

def _add(operands: List[Number]) -> Number:
    """Add all operands: a + b + c + ..."""
    return sum(operands)


def _multiply(operands: List[Number]) -> Number:
    """Multiply all operands: a * b * c * ..."""
    result = 1.0
    for x in operands:
        result *= x
    return result


def _min(operands: List[Number]) -> Number:
    """Minimum of all operands"""
    return min(operands)


def _max(operands: List[Number]) -> Number:
    """Maximum of all operands"""
    return max(operands)


def _sum(operands: List[Number]) -> Number:
    """Sum of all operands (alias for add)"""
    return sum(operands)


def _average(operands: List[Number]) -> Number:
    """Arithmetic mean of all operands"""
    return sum(operands) / len(operands)


def _hypot(operands: List[Number]) -> Number:
    """Euclidean distance: sqrt(x1^2 + x2^2 + ...)"""
    return math.hypot(*operands)


def _geometric_mean(operands: List[Number]) -> Number:
    """Geometric mean: (x1 * x2 * ... * xn)^(1/n). Raises error for negative values."""
    for x in operands:
        if x < 0:
            raise OperatorError("geometric_mean", f"Cannot compute geometric mean with negative value: {x}")
    return statistics.geometric_mean(operands)


def _harmonic_mean(operands: List[Number]) -> Number:
    """Harmonic mean: n / (1/x1 + 1/x2 + ... + 1/xn). Raises error for zero/negative values."""
    for x in operands:
        if x <= 0:
            raise OperatorError("harmonic_mean", f"Harmonic mean requires positive values, got: {x}")
    return statistics.harmonic_mean(operands)


def _variance(operands: List[Number]) -> Number:
    """Sample variance of operands. Requires at least 2 values."""
    if len(operands) < 2:
        raise OperatorError("variance", "Variance requires at least 2 values")
    return statistics.variance(operands)


def _std_dev(operands: List[Number]) -> Number:
    """Sample standard deviation of operands. Requires at least 2 values."""
    if len(operands) < 2:
        raise OperatorError("std_dev", "Standard deviation requires at least 2 values")
    return statistics.stdev(operands)


def _range(operands: List[Number]) -> Number:
    """Range: max - min"""
    return max(operands) - min(operands)


# =============================================================================
# Operator Registry
# =============================================================================

# Dictionary mapping operator names to Operator objects
_OPERATOR_REGISTRY: Dict[str, Operator] = {}


def _register(op: Operator) -> None:
    """Register an operator in the registry."""
    _OPERATOR_REGISTRY[op.name] = op


# Register all operators

# Unary operators (arity=1)
_register(Operator("negate", "Negate", "-", 1, 1, _negate, "Returns the negation of the operand: -x"))
_register(Operator("abs", "Absolute Value", "|x|", 1, 1, _abs, "Returns the absolute value of the operand"))
_register(Operator("sqrt", "Square Root", "sqrt", 1, 1, _sqrt, "Returns the square root (fails for negative input)"))
_register(Operator("square", "Square", "x^2", 1, 1, _square, "Returns the operand squared"))
_register(Operator("cube", "Cube", "x^3", 1, 1, _cube, "Returns the operand cubed"))
_register(Operator("reciprocal", "Reciprocal", "1/x", 1, 1, _reciprocal, "Returns 1 divided by the operand (fails for zero)"))
_register(Operator("floor", "Floor", "floor", 1, 1, _floor, "Returns the largest integer less than or equal to x"))
_register(Operator("ceil", "Ceiling", "ceil", 1, 1, _ceil, "Returns the smallest integer greater than or equal to x"))
_register(Operator("round", "Round", "round", 1, 1, _round, "Rounds to the nearest integer"))
_register(Operator("sign", "Sign", "sign", 1, 1, _sign, "Returns -1, 0, or 1 based on the sign of x"))
_register(Operator("ln", "Natural Log", "ln", 1, 1, _ln, "Returns the natural logarithm (fails for non-positive input)"))
_register(Operator("log10", "Log Base 10", "log10", 1, 1, _log10, "Returns the base-10 logarithm (fails for non-positive input)"))
_register(Operator("exp", "Exponential", "e^x", 1, 1, _exp, "Returns e raised to the power of x"))
_register(Operator("sin", "Sine", "sin", 1, 1, _sin, "Returns the sine of x (in radians)"))
_register(Operator("cos", "Cosine", "cos", 1, 1, _cos, "Returns the cosine of x (in radians)"))
_register(Operator("tan", "Tangent", "tan", 1, 1, _tan, "Returns the tangent of x (in radians)"))
_register(Operator("asin", "Arc Sine", "asin", 1, 1, _asin, "Returns the arc sine (fails if |x| > 1)"))
_register(Operator("acos", "Arc Cosine", "acos", 1, 1, _acos, "Returns the arc cosine (fails if |x| > 1)"))
_register(Operator("atan", "Arc Tangent", "atan", 1, 1, _atan, "Returns the arc tangent of x"))
_register(Operator("degrees", "Degrees", "deg", 1, 1, _degrees, "Converts radians to degrees"))
_register(Operator("radians", "Radians", "rad", 1, 1, _radians, "Converts degrees to radians"))

# Binary operators (arity=2)
_register(Operator("subtract", "Subtract", "-", 2, 2, _subtract, "Returns a - b"))
_register(Operator("divide", "Divide", "/", 2, 2, _divide, "Returns a / b (fails for division by zero)"))
_register(Operator("floor_divide", "Floor Divide", "//", 2, 2, _floor_divide, "Returns floor(a / b) (fails for division by zero)"))
_register(Operator("modulo", "Modulo", "%", 2, 2, _modulo, "Returns a % b (remainder) (fails for modulo by zero)"))
_register(Operator("power", "Power", "^", 2, 2, _power, "Returns a raised to the power of b"))
_register(Operator("log", "Logarithm", "log_b", 2, 2, _log, "Returns logarithm of a with base b"))
_register(Operator("atan2", "Arc Tangent 2", "atan2", 2, 2, _atan2, "Returns arc tangent of y/x, using signs to determine quadrant"))

# Variadic operators (arity>=2, unlimited)
_register(Operator("add", "Add", "+", 2, None, _add, "Returns the sum of all operands"))
_register(Operator("multiply", "Multiply", "*", 2, None, _multiply, "Returns the product of all operands"))
_register(Operator("min", "Minimum", "min", 2, None, _min, "Returns the minimum of all operands"))
_register(Operator("max", "Maximum", "max", 2, None, _max, "Returns the maximum of all operands"))
_register(Operator("sum", "Sum", "sum", 2, None, _sum, "Returns the sum of all operands (alias for add)"))
_register(Operator("average", "Average", "avg", 2, None, _average, "Returns the arithmetic mean of all operands"))
_register(Operator("hypot", "Hypotenuse", "hypot", 2, None, _hypot, "Returns Euclidean distance: sqrt(x1^2 + x2^2 + ...)"))
_register(Operator("geometric_mean", "Geometric Mean", "geomean", 2, None, _geometric_mean, "Returns geometric mean (fails for negative values)"))
_register(Operator("harmonic_mean", "Harmonic Mean", "harmean", 2, None, _harmonic_mean, "Returns harmonic mean (fails for zero/negative values)"))
_register(Operator("variance", "Variance", "var", 2, None, _variance, "Returns sample variance (requires >= 2 values)"))
_register(Operator("std_dev", "Standard Deviation", "stdev", 2, None, _std_dev, "Returns sample standard deviation (requires >= 2 values)"))
_register(Operator("range", "Range", "range", 2, None, _range, "Returns max - min of all operands"))


# =============================================================================
# Public API
# =============================================================================

def get_operator(name: str) -> Optional[Operator]:
    """Get an operator by name.
    
    Args:
        name: The operator name (e.g., "add", "sqrt")
        
    Returns:
        The Operator object, or None if not found.
    """
    return _OPERATOR_REGISTRY.get(name)


def execute_operator(name: str, operands: List[Number]) -> Number:
    """Execute an operator with the given operands.
    
    Args:
        name: The operator name
        operands: List of numeric operands
        
    Returns:
        The computed result
        
    Raises:
        ValueError: If operator not found or arity mismatch
        OperatorError: If operator execution fails (e.g., sqrt of negative)
    """
    op = get_operator(name)
    if op is None:
        raise ValueError(f"Unknown operator: '{name}'")
    
    # Validate arity
    count = len(operands)
    if count < op.min_arity:
        raise ValueError(
            f"Operator '{name}' requires at least {op.min_arity} operand(s), got {count}"
        )
    if op.max_arity is not None and count > op.max_arity:
        raise ValueError(
            f"Operator '{name}' accepts at most {op.max_arity} operand(s), got {count}"
        )
    
    # Execute
    return op.execute(operands)


def get_all_operators() -> List[Operator]:
    """Get all registered operators.
    
    Returns:
        List of all Operator objects.
    """
    return list(_OPERATOR_REGISTRY.values())


def get_operators_by_arity(arity: int) -> List[Operator]:
    """Get operators that accept a specific number of operands.
    
    Args:
        arity: The exact number of operands
        
    Returns:
        List of operators that can accept exactly that many operands.
    """
    result = []
    for op in _OPERATOR_REGISTRY.values():
        if op.min_arity <= arity:
            if op.max_arity is None or op.max_arity >= arity:
                result.append(op)
    return result


def get_operator_names() -> List[str]:
    """Get list of all operator names.
    
    Returns:
        Sorted list of operator names.
    """
    return sorted(_OPERATOR_REGISTRY.keys())


def validate_operator_arity(name: str, operand_count: int) -> Optional[str]:
    """Validate that an operator can accept the given number of operands.
    
    Args:
        name: The operator name
        operand_count: The number of operands to be provided
        
    Returns:
        Error message if invalid, None if valid.
    """
    op = get_operator(name)
    if op is None:
        return f"Unknown operator: '{name}'. Valid operators: {', '.join(get_operator_names())}"
    
    if operand_count < op.min_arity:
        return f"Operator '{name}' requires at least {op.min_arity} operand(s), got {operand_count}"
    
    if op.max_arity is not None and operand_count > op.max_arity:
        return f"Operator '{name}' accepts at most {op.max_arity} operand(s), got {operand_count}"
    
    return None
