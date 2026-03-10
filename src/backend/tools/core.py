"""Core tool abstractions and registry.

Provides the base Tool class, the WorkflowTool convenience base class
(which eliminates boilerplate for tools that load a workflow by ID),
and the ToolRegistry for dispatching tool calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


def tool_error(error: str, error_code: str = "TOOL_ERROR") -> Dict[str, Any]:
    """Create a standardized tool error response.

    All tool error responses should use this helper to ensure a consistent
    format across the codebase.  The canonical shape is:
        {"success": False, "error": "<human-readable>", "error_code": "<MACHINE_CODE>"}

    Args:
        error: Human-readable error description.
        error_code: Machine-readable code for programmatic handling.
    """
    return {
        "success": False,
        "error": error,
        "error_code": error_code,
    }


@dataclass
class ToolParameter:
    """Describes a single parameter for an LLM-callable tool.

    Basic parameters need only name, type, and description.
    Rich JSON Schema features (enum, items, nested properties, oneOf) are
    supported via optional fields so tool classes can fully describe their
    schemas without a separate hand-maintained file.
    """
    name: str
    type: str
    description: str
    required: bool = True
    # Fixed set of allowed string values (e.g., node types)
    enum: Optional[List[str]] = None
    # Schema for array element items (e.g., {"type": "object", "properties": ...})
    items: Optional[Dict[str, Any]] = None
    # Nested properties for object-type parameters
    properties: Optional[Dict[str, Any]] = None
    # additionalProperties constraint for object-type parameters
    additional_properties: Optional[Dict[str, Any]] = None
    # oneOf / anyOf for union types (e.g., simple vs compound condition)
    one_of: Optional[List[Dict[str, Any]]] = None
    # Numeric constraints
    minimum: Optional[int] = None
    maximum: Optional[int] = None

    def to_json_schema(self) -> Dict[str, Any]:
        """Convert this parameter to a JSON Schema property dict."""
        prop: Dict[str, Any] = {"description": self.description}
        # oneOf replaces the top-level type (union types)
        if self.one_of:
            prop["oneOf"] = self.one_of
        else:
            prop["type"] = self.type
        if self.enum is not None:
            prop["enum"] = self.enum
        if self.items is not None:
            prop["items"] = self.items
        if self.properties is not None:
            prop["properties"] = self.properties
        if self.additional_properties is not None:
            prop["additionalProperties"] = self.additional_properties
        if self.minimum is not None:
            prop["minimum"] = self.minimum
        if self.maximum is not None:
            prop["maximum"] = self.maximum
        return prop


class Tool:
    """Base class for all LLM-callable tools.

    Each tool declares ``name``, ``description``, and ``parameters``
    (a list of ToolParameter objects).  Tools with complex nested schemas
    that are awkward to express via ToolParameter can set
    ``_schema_override`` — a raw JSON Schema dict for the parameters
    property — which takes precedence in ``to_anthropic_schema()``.
    """

    name: str
    description: str
    parameters: List[ToolParameter]
    # Optional: raw JSON Schema dict that replaces auto-generated parameters.
    # Use this for tools with deeply nested schemas (e.g., add_node's condition).
    _schema_override: Optional[Dict[str, Any]] = None

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        raise NotImplementedError

    def to_anthropic_schema(self) -> Dict[str, Any]:
        """Generate Anthropic function-calling schema from this tool's metadata.

        Returns a dict in the format expected by the Anthropic API:
        ``{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}``

        If ``_schema_override`` is set, it is used as-is for the parameters
        property.  Otherwise, the schema is auto-generated from ``self.parameters``.
        """
        if self._schema_override is not None:
            params_schema = self._schema_override
        else:
            properties: Dict[str, Any] = {}
            required: List[str] = []
            for param in self.parameters:
                properties[param.name] = param.to_json_schema()
                if param.required:
                    required.append(param.name)
            params_schema = {
                "type": "object",
                "properties": properties,
                "required": required,
            }

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": params_schema,
            },
        }


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

    def all_tools(self) -> List[Tool]:
        """Return all registered tools in registration order."""
        return list(self._tools.values())

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
