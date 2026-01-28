"""Tool registry and workflow tools."""

from .core import Tool, ToolParameter, ToolRegistry
from .discovery import build_tool_registry, discover_tool_classes
from .workflow_analysis import AnalyzeWorkflowTool, PublishLatestAnalysisTool
from .workflow_edit import (
    GetCurrentWorkflowTool,
    AddNodeTool,
    ModifyNodeTool,
    DeleteNodeTool,
    AddConnectionTool,
    DeleteConnectionTool,
    BatchEditWorkflowTool,
)
from .workflow_input import (
    AddWorkflowVariableTool,
    ListWorkflowVariablesTool,
    ModifyWorkflowVariableTool,
    RemoveWorkflowVariableTool,
    # Backwards compatibility aliases
    AddWorkflowInputTool,
    ListWorkflowInputsTool,
    ModifyWorkflowInputTool,
    RemoveWorkflowInputTool,
)
from .workflow_output import SetWorkflowOutputTool
from .validate_workflow import ValidateWorkflowTool
from .workflow_library import ListWorkflowsInLibrary

__all__ = [
    "Tool",
    "ToolParameter",
    "ToolRegistry",
    "build_tool_registry",
    "discover_tool_classes",
    "AnalyzeWorkflowTool",
    "PublishLatestAnalysisTool",
    "GetCurrentWorkflowTool",
    "AddNodeTool",
    "ModifyNodeTool",
    "DeleteNodeTool",
    "AddConnectionTool",
    "DeleteConnectionTool",
    "BatchEditWorkflowTool",
    # New variable tool names
    "AddWorkflowVariableTool",
    "ListWorkflowVariablesTool",
    "ModifyWorkflowVariableTool",
    "RemoveWorkflowVariableTool",
    # Backwards compatibility aliases
    "AddWorkflowInputTool",
    "ListWorkflowInputsTool",
    "ModifyWorkflowInputTool",
    "RemoveWorkflowInputTool",
    # Output tool
    "SetWorkflowOutputTool",
    "ValidateWorkflowTool",
    "ListWorkflowsInLibrary",
]
