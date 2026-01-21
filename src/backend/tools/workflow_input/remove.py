"""Remove workflow input tool."""

from __future__ import annotations

from typing import Any, Dict

from ..core import Tool, ToolParameter
from .helpers import ensure_workflow_analysis, normalize_input_name


class RemoveWorkflowInputTool(Tool):
    """Remove a registered workflow input."""

    name = "remove_workflow_input"
    description = (
        "Remove a registered workflow input by name (case-insensitive). "
        "Note: This does NOT remove input_ref from nodes that reference it - "
        "you should check if nodes reference this input first."
    )
    parameters = [
        ToolParameter(
            "name",
            "string",
            "Name of the input to remove (case-insensitive)",
            required=True,
        ),
    ]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        workflow_analysis = ensure_workflow_analysis(session_state)
        inputs = workflow_analysis.get("inputs", [])

        name = args.get("name")
        if not name or not isinstance(name, str):
            return {"success": False, "error": "Input 'name' is required"}

        normalized_name = normalize_input_name(name)
        original_length = len(inputs)

        workflow_analysis["inputs"] = [
            inp for inp in inputs
            if normalize_input_name(inp.get("name", "")) != normalized_name
        ]

        if len(workflow_analysis["inputs"]) == original_length:
            return {
                "success": False,
                "error": f"Input '{name}' not found"
            }

        return {
            "success": True,
            "message": f"Removed input '{name}'",
            "workflow_analysis": workflow_analysis,
        }
