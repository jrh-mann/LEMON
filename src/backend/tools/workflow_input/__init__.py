"""Workflow variable tools."""

from .add import AddWorkflowVariableTool, AddWorkflowInputTool
from .list import ListWorkflowVariablesTool, ListWorkflowInputsTool
from .modify import ModifyWorkflowVariableTool, ModifyWorkflowInputTool
from .remove import RemoveWorkflowVariableTool, RemoveWorkflowInputTool

__all__ = [
    # New names
    "AddWorkflowVariableTool",
    "ListWorkflowVariablesTool",
    "ModifyWorkflowVariableTool",
    "RemoveWorkflowVariableTool",
    # Backwards compatibility aliases
    "AddWorkflowInputTool",
    "ListWorkflowInputsTool",
    "ModifyWorkflowInputTool",
    "RemoveWorkflowInputTool",
]
