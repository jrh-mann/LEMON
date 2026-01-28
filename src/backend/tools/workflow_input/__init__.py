"""Workflow variable tools."""

from .add import AddWorkflowVariableTool, AddWorkflowInputTool
from .list import ListWorkflowVariablesTool, ListWorkflowInputsTool
from .remove import RemoveWorkflowVariableTool, RemoveWorkflowInputTool

__all__ = [
    # New names
    "AddWorkflowVariableTool",
    "ListWorkflowVariablesTool",
    "RemoveWorkflowVariableTool",
    # Backwards compatibility aliases
    "AddWorkflowInputTool",
    "ListWorkflowInputsTool",
    "RemoveWorkflowInputTool",
]
