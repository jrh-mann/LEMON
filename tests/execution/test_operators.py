"""Tests for the operator registry (mathematical operations for calculation nodes)."""

import math
import pytest
from src.backend.execution.operators import (
    execute_operator,
    get_operator,
    get_operator_names,
    get_all_operators,
    validate_operator_arity,
    OperatorError,
)


class TestOperatorRegistry:
    """Test operator registry metadata and lookup functions."""

    def test_get_operator_names_returns_all_operators(self):
        """Verify all 40 operators are registered."""
        names = get_operator_names()
        assert len(names) == 40
        # Spot check some expected operators
        assert "add" in names
        assert "subtract" in names
        assert "sqrt" in names
        assert "average" in names

    def test_get_operator_returns_metadata(self):
        """Test getting operator metadata."""
        op = get_operator("add")
        assert op is not None
        assert op.name == "add"
        assert op.min_arity == 2
        assert op.max_arity is None  # variadic
        assert op.description is not None

    def test_get_operator_unknown_operator(self):
        """Test that unknown operator returns None."""
        op = get_operator("nonexistent_operator")
        assert op is None

    def test_get_all_operators(self):
        """Test getting all operators."""
        ops = get_all_operators()
        assert len(ops) == 40


class TestValidateOperatorArity:
    """Test operand count validation."""

    def test_unary_operator_accepts_one_operand(self):
        """Unary operators require exactly 1 operand."""
        # Should return None (valid)
        assert validate_operator_arity("sqrt", 1) is None
        assert validate_operator_arity("negate", 1) is None
        assert validate_operator_arity("abs", 1) is None

    def test_unary_operator_rejects_multiple_operands(self):
        """Unary operators reject more than 1 operand."""
        error = validate_operator_arity("sqrt", 2)
        assert error is not None
        assert "at most 1" in error

    def test_binary_operator_accepts_two_operands(self):
        """Binary operators require exactly 2 operands."""
        assert validate_operator_arity("subtract", 2) is None
        assert validate_operator_arity("divide", 2) is None
        assert validate_operator_arity("power", 2) is None

    def test_binary_operator_rejects_wrong_count(self):
        """Binary operators reject wrong operand count."""
        error1 = validate_operator_arity("divide", 1)
        assert error1 is not None
        assert "at least 2" in error1
        
        error2 = validate_operator_arity("divide", 3)
        assert error2 is not None
        assert "at most 2" in error2

    def test_variadic_operator_accepts_two_or_more(self):
        """Variadic operators accept 2+ operands."""
        assert validate_operator_arity("add", 2) is None
        assert validate_operator_arity("add", 5) is None
        assert validate_operator_arity("add", 100) is None

    def test_variadic_operator_rejects_less_than_two(self):
        """Variadic operators reject fewer than 2 operands."""
        error = validate_operator_arity("add", 1)
        assert error is not None
        assert "at least 2" in error


class TestUnaryOperators:
    """Test unary operators (1 operand)."""

    def test_negate(self):
        """Test negation operator."""
        assert execute_operator("negate", [5]) == -5
        assert execute_operator("negate", [-3]) == 3
        assert execute_operator("negate", [0]) == 0

    def test_abs(self):
        """Test absolute value operator."""
        assert execute_operator("abs", [5]) == 5
        assert execute_operator("abs", [-5]) == 5
        assert execute_operator("abs", [0]) == 0

    def test_sqrt(self):
        """Test square root operator."""
        assert execute_operator("sqrt", [16]) == 4.0
        assert execute_operator("sqrt", [2]) == pytest.approx(math.sqrt(2))
        assert execute_operator("sqrt", [0]) == 0.0

    def test_sqrt_negative_raises_error(self):
        """Test that sqrt of negative number raises error."""
        with pytest.raises(OperatorError, match="square root of negative"):
            execute_operator("sqrt", [-4])

    def test_square(self):
        """Test square operator."""
        assert execute_operator("square", [3]) == 9
        assert execute_operator("square", [-4]) == 16
        assert execute_operator("square", [0]) == 0

    def test_cube(self):
        """Test cube operator."""
        assert execute_operator("cube", [2]) == 8
        assert execute_operator("cube", [-2]) == -8
        assert execute_operator("cube", [0]) == 0

    def test_reciprocal(self):
        """Test reciprocal (1/x) operator."""
        assert execute_operator("reciprocal", [2]) == 0.5
        assert execute_operator("reciprocal", [4]) == 0.25
        assert execute_operator("reciprocal", [-2]) == -0.5

    def test_reciprocal_zero_raises_error(self):
        """Test that reciprocal of zero raises error."""
        with pytest.raises(OperatorError, match="reciprocal of zero"):
            execute_operator("reciprocal", [0])

    def test_floor(self):
        """Test floor operator."""
        assert execute_operator("floor", [3.7]) == 3
        assert execute_operator("floor", [-3.7]) == -4
        assert execute_operator("floor", [5.0]) == 5

    def test_ceil(self):
        """Test ceiling operator."""
        assert execute_operator("ceil", [3.2]) == 4
        assert execute_operator("ceil", [-3.2]) == -3
        assert execute_operator("ceil", [5.0]) == 5

    def test_round(self):
        """Test round operator."""
        assert execute_operator("round", [3.5]) == 4
        assert execute_operator("round", [3.4]) == 3
        assert execute_operator("round", [-3.5]) == -4

    def test_sign(self):
        """Test sign operator."""
        assert execute_operator("sign", [10]) == 1
        assert execute_operator("sign", [-10]) == -1
        assert execute_operator("sign", [0]) == 0

    def test_ln(self):
        """Test natural logarithm operator."""
        assert execute_operator("ln", [math.e]) == pytest.approx(1.0)
        assert execute_operator("ln", [1]) == 0.0

    def test_ln_non_positive_raises_error(self):
        """Test that ln of non-positive number raises error."""
        with pytest.raises(OperatorError, match="natural log of non-positive"):
            execute_operator("ln", [0])
        with pytest.raises(OperatorError, match="natural log of non-positive"):
            execute_operator("ln", [-1])

    def test_log10(self):
        """Test base-10 logarithm operator."""
        assert execute_operator("log10", [100]) == 2.0
        assert execute_operator("log10", [1000]) == 3.0

    def test_exp(self):
        """Test exponential (e^x) operator."""
        assert execute_operator("exp", [0]) == 1.0
        assert execute_operator("exp", [1]) == pytest.approx(math.e)

    def test_trig_functions(self):
        """Test trigonometric functions."""
        # sin, cos, tan
        assert execute_operator("sin", [0]) == pytest.approx(0.0)
        assert execute_operator("cos", [0]) == pytest.approx(1.0)
        assert execute_operator("tan", [0]) == pytest.approx(0.0)
        # At pi/2
        assert execute_operator("sin", [math.pi / 2]) == pytest.approx(1.0)
        assert execute_operator("cos", [math.pi / 2]) == pytest.approx(0.0, abs=1e-10)

    def test_inverse_trig_functions(self):
        """Test inverse trigonometric functions."""
        assert execute_operator("asin", [0]) == pytest.approx(0.0)
        assert execute_operator("acos", [1]) == pytest.approx(0.0)
        assert execute_operator("atan", [0]) == pytest.approx(0.0)
        assert execute_operator("asin", [1]) == pytest.approx(math.pi / 2)

    def test_degrees(self):
        """Test radians to degrees conversion."""
        assert execute_operator("degrees", [math.pi]) == pytest.approx(180.0)
        assert execute_operator("degrees", [math.pi / 2]) == pytest.approx(90.0)

    def test_radians(self):
        """Test degrees to radians conversion."""
        assert execute_operator("radians", [180]) == pytest.approx(math.pi)
        assert execute_operator("radians", [90]) == pytest.approx(math.pi / 2)


class TestBinaryOperators:
    """Test binary operators (2 operands)."""

    def test_subtract(self):
        """Test subtraction operator."""
        assert execute_operator("subtract", [10, 3]) == 7
        assert execute_operator("subtract", [5, 8]) == -3
        assert execute_operator("subtract", [0, 0]) == 0

    def test_divide(self):
        """Test division operator."""
        assert execute_operator("divide", [10, 2]) == 5.0
        assert execute_operator("divide", [7, 2]) == 3.5
        assert execute_operator("divide", [-6, 3]) == -2.0

    def test_divide_by_zero_raises_error(self):
        """Test that division by zero raises error."""
        with pytest.raises(OperatorError, match="Division by zero"):
            execute_operator("divide", [10, 0])

    def test_floor_divide(self):
        """Test floor division operator."""
        assert execute_operator("floor_divide", [7, 2]) == 3
        assert execute_operator("floor_divide", [10, 3]) == 3
        assert execute_operator("floor_divide", [-7, 2]) == -4

    def test_modulo(self):
        """Test modulo operator."""
        assert execute_operator("modulo", [10, 3]) == 1
        assert execute_operator("modulo", [15, 5]) == 0
        assert execute_operator("modulo", [7, 4]) == 3

    def test_power(self):
        """Test power operator."""
        assert execute_operator("power", [2, 3]) == 8
        assert execute_operator("power", [5, 2]) == 25
        assert execute_operator("power", [9, 0.5]) == 3.0

    def test_log(self):
        """Test logarithm with base operator."""
        assert execute_operator("log", [8, 2]) == 3.0
        assert execute_operator("log", [100, 10]) == 2.0
        assert execute_operator("log", [27, 3]) == pytest.approx(3.0)

    def test_atan2(self):
        """Test atan2 operator (y, x)."""
        assert execute_operator("atan2", [1, 1]) == pytest.approx(math.pi / 4)
        assert execute_operator("atan2", [0, 1]) == pytest.approx(0.0)
        assert execute_operator("atan2", [1, 0]) == pytest.approx(math.pi / 2)


class TestVariadicOperators:
    """Test variadic operators (2+ operands)."""

    def test_add(self):
        """Test addition operator."""
        assert execute_operator("add", [1, 2]) == 3
        assert execute_operator("add", [1, 2, 3]) == 6
        assert execute_operator("add", [1, 2, 3, 4, 5]) == 15
        assert execute_operator("add", [-1, 1]) == 0

    def test_multiply(self):
        """Test multiplication operator."""
        assert execute_operator("multiply", [2, 3]) == 6
        assert execute_operator("multiply", [2, 3, 4]) == 24
        assert execute_operator("multiply", [1, 2, 3, 4, 5]) == 120

    def test_min(self):
        """Test minimum operator."""
        assert execute_operator("min", [3, 1, 4, 1, 5]) == 1
        assert execute_operator("min", [10, 20]) == 10
        assert execute_operator("min", [-5, -10, -3]) == -10

    def test_max(self):
        """Test maximum operator."""
        assert execute_operator("max", [3, 1, 4, 1, 5]) == 5
        assert execute_operator("max", [10, 20]) == 20
        assert execute_operator("max", [-5, -10, -3]) == -3

    def test_sum(self):
        """Test sum operator (alias for add)."""
        assert execute_operator("sum", [1, 2, 3]) == 6
        assert execute_operator("sum", [10, 20, 30, 40]) == 100

    def test_average(self):
        """Test average operator."""
        assert execute_operator("average", [2, 4]) == 3.0
        assert execute_operator("average", [1, 2, 3, 4, 5]) == 3.0
        assert execute_operator("average", [10, 20, 30]) == 20.0

    def test_hypot(self):
        """Test hypotenuse operator."""
        assert execute_operator("hypot", [3, 4]) == 5.0
        assert execute_operator("hypot", [5, 12]) == 13.0
        # 3D case
        assert execute_operator("hypot", [1, 2, 2]) == 3.0

    def test_geometric_mean(self):
        """Test geometric mean operator."""
        assert execute_operator("geometric_mean", [4, 9]) == pytest.approx(6.0)
        assert execute_operator("geometric_mean", [1, 2, 4]) == 2.0

    def test_harmonic_mean(self):
        """Test harmonic mean operator."""
        assert execute_operator("harmonic_mean", [1, 2]) == pytest.approx(4/3)
        assert execute_operator("harmonic_mean", [2, 4, 8]) == pytest.approx(24/7)

    def test_variance(self):
        """Test variance operator."""
        # variance([2, 4, 6]) = ((2-4)^2 + (4-4)^2 + (6-4)^2) / 2 = 4
        assert execute_operator("variance", [2, 4, 6]) == pytest.approx(4.0)

    def test_std_dev(self):
        """Test standard deviation operator."""
        # std_dev([2, 4, 6]) = sqrt(4) = 2
        assert execute_operator("std_dev", [2, 4, 6]) == pytest.approx(2.0)

    def test_range(self):
        """Test range operator (max - min)."""
        assert execute_operator("range", [1, 5, 3, 9, 2]) == 8
        assert execute_operator("range", [10, 20]) == 10
        assert execute_operator("range", [-5, 5]) == 10


class TestUnknownOperator:
    """Test behavior with unknown operators."""

    def test_unknown_operator_raises_error(self):
        """Test that unknown operator raises ValueError."""
        with pytest.raises(ValueError, match="Unknown operator"):
            execute_operator("nonexistent", [1, 2])

    def test_validate_unknown_operator_returns_error(self):
        """Test that validating unknown operator returns error message."""
        error = validate_operator_arity("nonexistent", 2)
        assert error is not None
        assert "Unknown operator" in error


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_operators_handle_floats(self):
        """Test that operators handle float inputs correctly."""
        assert execute_operator("add", [1.5, 2.5]) == 4.0
        assert execute_operator("multiply", [0.5, 4.0]) == 2.0
        assert execute_operator("power", [4.0, 0.5]) == 2.0

    def test_operators_handle_negative_numbers(self):
        """Test that operators handle negative numbers correctly."""
        assert execute_operator("add", [-1, -2, -3]) == -6
        assert execute_operator("multiply", [-2, 3]) == -6
        assert execute_operator("subtract", [-5, -3]) == -2

    def test_operators_handle_zero(self):
        """Test that operators handle zero correctly."""
        assert execute_operator("add", [0, 0]) == 0
        assert execute_operator("multiply", [0, 100]) == 0
        assert execute_operator("power", [0, 5]) == 0
        assert execute_operator("power", [5, 0]) == 1

    def test_very_large_numbers(self):
        """Test operators with very large numbers."""
        large = 10 ** 10
        assert execute_operator("add", [large, large]) == 2 * large
        assert execute_operator("multiply", [1000000, 1000000]) == 10 ** 12

    def test_very_small_numbers(self):
        """Test operators with very small numbers."""
        small = 10 ** -10
        assert execute_operator("add", [small, small]) == pytest.approx(2 * small)
        assert execute_operator("multiply", [small, 1000]) == pytest.approx(10 ** -7)
