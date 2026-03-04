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
    # Full JSON Schema dict for this property.  When set, replaces the
    # auto-generated {"type": …, "description": …}.  Use for complex
    # types: enum, oneOf, nested objects, arrays with item schemas.
    schema_override: Optional[Dict[str, Any]] = None


class Tool:
    """Base class for all LLM-callable tools.

    Subclasses define class-level metadata that the framework uses
    to auto-generate JSON schemas, MCP wrappers, system-prompt hints,
    and category membership — eliminating the need to register a tool
    in multiple files.
    """

    name: str
    description: str
    parameters: List[ToolParameter]

    # Category for grouping — replaces hardcoded frozensets in constants.py.
    # Values: "workflow_edit", "workflow_input", "workflow_library", etc.
    category: str = ""

    # System prompt hint — auto-injected into "WHEN TO CALL TOOLS" section.
    # Example: "ADD/CREATE (node) → call add_node with workflow_id"
    prompt_hint: str = ""

    # ------------------------------------------------------------------ #
    # Schema generation
    # ------------------------------------------------------------------ #

    @classmethod
    def json_schema(cls) -> Dict[str, Any]:
        """Auto-generate an Anthropic function-calling schema.

        Reads ``cls.parameters`` (a list of :class:`ToolParameter`) and
        produces the ``{"type": "function", "function": {…}}`` dict
        expected by the Anthropic API.
        """
        properties: Dict[str, Any] = {}
        required: List[str] = []
        for p in cls.parameters:
            if p.schema_override:
                prop = {**p.schema_override}
                if "description" not in prop:
                    prop["description"] = p.description
            else:
                prop = {"type": p.type, "description": p.description}
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        return {
            "type": "function",
            "function": {
                "name": cls.name,
                "description": cls.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

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


def extract_session_deps(
    kwargs: Dict[str, Any],
    *,
    action: str = "perform action",
) -> Tuple[Dict[str, Any], Any, str, Optional[Dict[str, Any]]]:
    """Extract session_state, workflow_store, and user_id from kwargs.

    This eliminates the ~15 lines of repeated validation that every
    library-level tool (create, save, list) duplicates.

    Args:
        kwargs: The **kwargs passed to Tool.execute()
        action: Human-readable action name for error messages
            (e.g., "create workflow", "list workflows").

    Returns:
        ``(session_state, workflow_store, user_id, error)`` where *error*
        is ``None`` on success, or a dict the caller should return directly.
    """
    session_state = kwargs.get("session_state", {})
    if not session_state:
        return {}, None, "", {
            "success": False,
            "error": "No session state provided",
            "error_code": "NO_SESSION",
            "message": f"Unable to {action} - no session context.",
        }

    workflow_store = session_state.get("workflow_store")
    user_id = session_state.get("user_id")

    if not workflow_store:
        return session_state, None, "", {
            "success": False,
            "error": "No workflow_store in session",
            "error_code": "NO_STORE",
            "message": f"Unable to {action} - storage not available.",
        }

    if not user_id:
        return session_state, workflow_store, "", {
            "success": False,
            "error": "No user_id in session",
            "error_code": "NO_USER",
            "message": f"Unable to {action} - user not authenticated.",
        }

    return session_state, workflow_store, user_id, None
