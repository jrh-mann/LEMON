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
        "add_workflow_variable",
        "list_workflow_variables",
        "modify_workflow_variable",
        "remove_workflow_variable",
    }
)

# Tools that create or modify workflow library entries
WORKFLOW_LIBRARY_TOOLS = frozenset(
    {
        "create_workflow",
        "list_workflows_in_library",
    }
)

