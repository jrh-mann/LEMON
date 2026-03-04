"""Shared tool constants.

Tool category sets (WORKFLOW_EDIT_TOOLS, etc.) are derived from the
``category`` class attribute on each Tool subclass via auto-discovery.
Type-mapping constants remain hand-written (not tool-specific).
"""

from __future__ import annotations

from functools import lru_cache
from typing import FrozenSet


# ------------------------------------------------------------------ #
# Category-based tool sets — auto-discovered from Tool.category
# ------------------------------------------------------------------ #

@lru_cache(maxsize=None)
def _tools_for_category(cat: str) -> FrozenSet[str]:
    """Return the frozenset of tool names whose category matches *cat*."""
    from .discovery import discover_tool_classes

    return frozenset(
        cls.name for cls in discover_tool_classes()
        if getattr(cls, "category", "") == cat
    )


# These module-level names are still imported everywhere, so we use a
# lazy descriptor that evaluates on first access.
class _LazyFrozenSet:
    """Descriptor that resolves to a frozenset on first attribute access."""

    def __init__(self, category: str) -> None:
        self._category = category
        self._value: FrozenSet[str] | None = None

    def __set_name__(self, owner: type, name: str) -> None:
        self._attr = name

    def __get__(self, obj: object, objtype: type | None = None) -> FrozenSet[str]:
        if self._value is None:
            self._value = _tools_for_category(self._category)
        return self._value


class _Constants:
    """Namespace holding lazily-resolved tool category frozensets."""

    WORKFLOW_EDIT_TOOLS = _LazyFrozenSet("workflow_edit")
    WORKFLOW_INPUT_TOOLS = _LazyFrozenSet("workflow_input")
    WORKFLOW_LIBRARY_TOOLS = _LazyFrozenSet("workflow_library")


_c = _Constants()

# Re-export as module-level names so existing ``from .constants import
# WORKFLOW_EDIT_TOOLS`` continues to work.  The descriptor fires on
# first attribute access, triggering discovery exactly once.
def __getattr__(name: str) -> FrozenSet[str]:
    if name == "WORKFLOW_EDIT_TOOLS":
        return _c.WORKFLOW_EDIT_TOOLS
    if name == "WORKFLOW_INPUT_TOOLS":
        return _c.WORKFLOW_INPUT_TOOLS
    if name == "WORKFLOW_LIBRARY_TOOLS":
        return _c.WORKFLOW_LIBRARY_TOOLS
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ------------------------------------------------------------------ #
# Variable / output type constants (not tool-specific)
# ------------------------------------------------------------------ #

# The set of valid internal types for workflow variables and outputs.
# Used by add_workflow_variable, modify_workflow_variable, set_workflow_output.
VALID_VARIABLE_TYPES = frozenset({"string", "number", "bool", "enum", "date"})

# Maps user-friendly type names (including common aliases) to the internal
# type string used by condition validation and the execution interpreter.
# 'number' is the unified numeric type (stored as float internally).
USER_TYPE_TO_INTERNAL = {
    "string": "string",
    "number": "number",         # Unified numeric type (stored as float)
    "integer": "number",        # Alias for number
    "boolean": "bool",
    "bool": "bool",             # Accept internal name directly
    "enum": "enum",
    "date": "date",
}

# Valid output types at the workflow level (create_workflow output_type param).
# This is distinct from VALID_VARIABLE_TYPES — workflows can return "json"
# but not "enum" or "date" at the top level.
VALID_WORKFLOW_OUTPUT_TYPES = frozenset({"string", "number", "bool", "json"})
