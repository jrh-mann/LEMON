"""Safe condition evaluation for workflow decisions.

This module provides a safe way to evaluate condition expressions in
workflow decision blocks. It uses Python's AST module to parse and
validate expressions before evaluation, preventing code injection.

Only a whitelist of operations is allowed:
- Comparisons: <, >, <=, >=, ==, !=
- Boolean operators: and, or, not
- Membership: in, not in
- Literals: numbers, strings, booleans, None, lists
- Variable references
"""

from __future__ import annotations

import ast
import operator
from typing import Any, Dict, List, Set

from lemon.core.exceptions import InvalidConditionError, UnknownVariableError


# Allowed comparison operators
COMPARISON_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda x, y: x in y,
    ast.NotIn: lambda x, y: x not in y,
}

# Allowed boolean operators
BOOL_OPS = {
    ast.And: lambda values: all(values),
    ast.Or: lambda values: any(values),
}

# Allowed unary operators
UNARY_OPS = {
    ast.Not: operator.not_,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


class ConditionEvaluator:
    """Safely evaluate decision condition expressions.

    This evaluator parses conditions using Python's AST and only allows
    a safe subset of operations. No function calls, attribute access,
    or other potentially dangerous operations are permitted.

    Usage:
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate("age >= 18", {"age": 25})
        # result = True

        # Validate before execution
        errors = evaluator.validate("age >= 18", ["age"])
        # errors = []
    """

    def evaluate(self, condition: str, context: Dict[str, Any]) -> bool:
        """Evaluate a condition expression against a context.

        Args:
            condition: A Python expression string (e.g., "age >= 18").
            context: Dictionary of variable name -> value.

        Returns:
            Boolean result of the condition.

        Raises:
            InvalidConditionError: If the condition is invalid or unsafe.
            UnknownVariableError: If condition references undefined variables.
        """
        # Strip whitespace to avoid indentation errors
        condition = condition.strip()

        try:
            tree = ast.parse(condition, mode="eval")
        except SyntaxError as e:
            raise InvalidConditionError(
                f"Invalid condition syntax: {e}",
                context={"condition": condition},
            )

        try:
            result = self._eval_node(tree.body, context)
            return bool(result)
        except UnknownVariableError:
            raise
        except Exception as e:
            raise InvalidConditionError(
                f"Error evaluating condition: {e}",
                context={"condition": condition},
            )

    def validate(self, condition: str, available_vars: List[str]) -> List[str]:
        """Validate a condition expression.

        Checks that:
        1. The condition is syntactically valid
        2. Only allowed operations are used
        3. All referenced variables are in available_vars

        Args:
            condition: The condition expression to validate.
            available_vars: List of variable names that are available.

        Returns:
            List of error messages. Empty if valid.
        """
        errors = []

        try:
            tree = ast.parse(condition, mode="eval")
        except SyntaxError as e:
            errors.append(f"Syntax error: {e}")
            return errors

        # Check for disallowed operations
        validation_errors = self._validate_node(tree.body)
        errors.extend(validation_errors)

        # Check for unknown variables
        referenced_vars = self._get_referenced_vars(tree.body)
        available_set = set(available_vars)
        unknown = referenced_vars - available_set
        if unknown:
            errors.append(f"Unknown variables: {', '.join(sorted(unknown))}")

        return errors

    def get_referenced_variables(self, condition: str) -> Set[str]:
        """Get all variable names referenced in a condition.

        Args:
            condition: The condition expression.

        Returns:
            Set of variable names.
        """
        try:
            tree = ast.parse(condition, mode="eval")
            return self._get_referenced_vars(tree.body)
        except SyntaxError:
            return set()

    # -------------------------------------------------------------------------
    # AST Evaluation
    # -------------------------------------------------------------------------

    def _eval_node(self, node: ast.AST, context: Dict[str, Any]) -> Any:
        """Recursively evaluate an AST node."""
        if isinstance(node, ast.Constant):
            return node.value

        elif isinstance(node, ast.Name):
            name = node.id
            if name not in context:
                raise UnknownVariableError(
                    f"Unknown variable: {name}",
                    context={"variable": name, "available": list(context.keys())},
                )
            return context[name]

        elif isinstance(node, ast.Compare):
            left = self._eval_node(node.left, context)
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval_node(comparator, context)
                op_func = COMPARISON_OPS.get(type(op))
                if op_func is None:
                    raise InvalidConditionError(
                        f"Unsupported comparison operator: {type(op).__name__}",
                    )
                if not op_func(left, right):
                    return False
                left = right
            return True

        elif isinstance(node, ast.BoolOp):
            op_func = BOOL_OPS.get(type(node.op))
            if op_func is None:
                raise InvalidConditionError(
                    f"Unsupported boolean operator: {type(node.op).__name__}",
                )
            values = [self._eval_node(v, context) for v in node.values]
            return op_func(values)

        elif isinstance(node, ast.UnaryOp):
            op_func = UNARY_OPS.get(type(node.op))
            if op_func is None:
                raise InvalidConditionError(
                    f"Unsupported unary operator: {type(node.op).__name__}",
                )
            operand = self._eval_node(node.operand, context)
            return op_func(operand)

        elif isinstance(node, ast.List):
            return [self._eval_node(elt, context) for elt in node.elts]

        elif isinstance(node, ast.Tuple):
            return tuple(self._eval_node(elt, context) for elt in node.elts)

        elif isinstance(node, ast.NameConstant):
            # For Python 3.7 compatibility (though we require 3.9+)
            return node.value

        else:
            raise InvalidConditionError(
                f"Unsupported expression type: {type(node).__name__}",
                context={"node": ast.dump(node)},
            )

    # -------------------------------------------------------------------------
    # AST Validation
    # -------------------------------------------------------------------------

    def _validate_node(self, node: ast.AST) -> List[str]:
        """Recursively validate an AST node."""
        errors = []

        if isinstance(node, ast.Constant):
            pass  # Constants are always allowed

        elif isinstance(node, ast.Name):
            pass  # Variable names are allowed (checked separately)

        elif isinstance(node, ast.Compare):
            errors.extend(self._validate_node(node.left))
            for op, comparator in zip(node.ops, node.comparators):
                if type(op) not in COMPARISON_OPS:
                    errors.append(f"Unsupported comparison operator: {type(op).__name__}")
                errors.extend(self._validate_node(comparator))

        elif isinstance(node, ast.BoolOp):
            if type(node.op) not in BOOL_OPS:
                errors.append(f"Unsupported boolean operator: {type(node.op).__name__}")
            for value in node.values:
                errors.extend(self._validate_node(value))

        elif isinstance(node, ast.UnaryOp):
            if type(node.op) not in UNARY_OPS:
                errors.append(f"Unsupported unary operator: {type(node.op).__name__}")
            errors.extend(self._validate_node(node.operand))

        elif isinstance(node, ast.List):
            for elt in node.elts:
                errors.extend(self._validate_node(elt))

        elif isinstance(node, ast.Tuple):
            for elt in node.elts:
                errors.extend(self._validate_node(elt))

        elif isinstance(node, ast.NameConstant):
            pass  # True, False, None

        elif isinstance(node, ast.Call):
            errors.append("Function calls are not allowed in conditions")

        elif isinstance(node, ast.Attribute):
            errors.append("Attribute access is not allowed in conditions")

        elif isinstance(node, ast.Subscript):
            errors.append("Subscript access is not allowed in conditions")

        elif isinstance(node, ast.BinOp):
            errors.append("Arithmetic operations are not allowed in conditions")

        else:
            errors.append(f"Unsupported expression type: {type(node).__name__}")

        return errors

    def _get_referenced_vars(self, node: ast.AST) -> Set[str]:
        """Get all variable names referenced in an AST node."""
        vars_found: Set[str] = set()

        if isinstance(node, ast.Name):
            vars_found.add(node.id)

        elif isinstance(node, ast.Compare):
            vars_found.update(self._get_referenced_vars(node.left))
            for comparator in node.comparators:
                vars_found.update(self._get_referenced_vars(comparator))

        elif isinstance(node, ast.BoolOp):
            for value in node.values:
                vars_found.update(self._get_referenced_vars(value))

        elif isinstance(node, ast.UnaryOp):
            vars_found.update(self._get_referenced_vars(node.operand))

        elif isinstance(node, ast.List):
            for elt in node.elts:
                vars_found.update(self._get_referenced_vars(elt))

        elif isinstance(node, ast.Tuple):
            for elt in node.elts:
                vars_found.update(self._get_referenced_vars(elt))

        return vars_found
