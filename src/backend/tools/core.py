"""Core tool abstractions and registry.

Provides the base Tool class, the WorkflowTool convenience base class
(which eliminates boilerplate for tools that load a workflow by ID),
and the ToolRegistry for dispatching tool calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ToolParameter:
    name: str
    type: str
    description: str
    required: bool = True


class Tool:
    """Base class for all LLM-callable tools."""

    name: str
    description: str
    parameters: List[ToolParameter]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        raise NotImplementedError


class WorkflowTool(Tool):
    """Base class for tools that operate on a workflow loaded from the database.

    Eliminates the repeated boilerplate of:
      1. Extracting session_state from kwargs
      2. Loading the workflow via load_workflow_for_tool()
      3. Extracting nodes/edges/variables from the loaded data
      4. Optionally initialising a WorkflowValidator

    Subclasses set `uses_validator = True` (the default) to get
    `self.validator` auto-created.  Override `uses_validator = False`
    for read-only or variable-only tools that don't need validation.
    """

    # Set to False in subclasses that don't need WorkflowValidator
    uses_validator: bool = True

    def __init__(self) -> None:
        if self.uses_validator:
            # Lazy import to avoid circular dependency at module level
            from ..validation.workflow_validator import WorkflowValidator
            self.validator = WorkflowValidator()

    def _load_workflow(
        self,
        args: Dict[str, Any],
        **kwargs: Any,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """Load a workflow from the database using the standard boilerplate.

        Extracts session_state from kwargs, reads workflow_id from args,
        and delegates to load_workflow_for_tool().

        Returns:
            (workflow_data, None) on success — workflow_data contains
            workflow_id, nodes, edges, variables, outputs, output_type, etc.
            (None, error_dict) on failure — caller should ``return error_dict``.
        """
        from .workflow_edit.helpers import load_workflow_for_tool

        session_state = kwargs.get("session_state", {})
        workflow_id = args.get("workflow_id")
        return load_workflow_for_tool(workflow_id, session_state)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool under its canonical name."""
        self._tools[tool.name] = tool

    def execute(self, name: str, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")
        return tool.execute(args, **kwargs)
