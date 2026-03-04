"""Shared tool constants.

Centralises tool name sets and type-mapping constants that are referenced
from multiple tool modules, avoiding duplicate definitions.
"""

from __future__ import annotations

WORKFLOW_EDIT_TOOLS = frozenset(
    {
        "add_node",
        "modify_node",
        "delete_node",
        "add_connection",
        "delete_connection",
        "batch_edit_workflow",
        "highlight_node",
    }
)

WORKFLOW_INPUT_TOOLS = frozenset(
    {
        "add_workflow_variable",
        "list_workflow_variables",
        "modify_workflow_variable",
        "remove_workflow_variable",
        "set_workflow_output",
    }
)

# Tools that create or modify workflow library entries
WORKFLOW_LIBRARY_TOOLS = frozenset(
    {
        "create_workflow",
        "save_workflow_to_library",
        "list_workflows_in_library",
    }
)


# ---------------------------------------------------------------------------
# Variable / output type constants
# ---------------------------------------------------------------------------

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


