"""Shared tool name constants."""

from __future__ import annotations

WORKFLOW_EDIT_TOOLS = frozenset(
    {
        "add_node",
        "modify_node",
        "delete_node",
        "add_connection",
        "delete_connection",
        "batch_edit_workflow",
    }
)

WORKFLOW_INPUT_TOOLS = frozenset(
    {
        # New names
        "add_workflow_variable",
        "list_workflow_variables",
        "remove_workflow_variable",
        # Legacy names (for backwards compatibility)
        "add_workflow_input",
        "list_workflow_inputs",
        "remove_workflow_input",
    }
)

