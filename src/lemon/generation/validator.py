"""Code validation utilities (placeholder; expanded later)."""

from __future__ import annotations

import ast


def has_entrypoint_function(code: str, *, function_name: str = "determine_workflow_outcome") -> bool:
    """Check whether `code` defines the required entrypoint function."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False

    return any(
        isinstance(node, ast.FunctionDef) and node.name == function_name
        for node in ast.walk(tree)
    )


