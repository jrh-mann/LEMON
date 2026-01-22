"""Modify node tool."""

from __future__ import annotations

from typing import Any, Dict

from ...validation.workflow_validator import WorkflowValidator
from ..core import Tool, ToolParameter
from .helpers import input_ref_error


class ModifyNodeTool(Tool):
    """Modify an existing node's properties."""

    name = "modify_node"
    description = "Update an existing node's label, type, or position."
    parameters = [
        ToolParameter("node_id", "string", "ID of the node to modify", required=True),
        ToolParameter("label", "string", "New label text", required=False),
        ToolParameter("type", "string", "New node type", required=False),
        ToolParameter("x", "number", "New X coordinate", required=False),
        ToolParameter("y", "number", "New Y coordinate", required=False),
        ToolParameter(
            "input_ref",
            "string",
            "Optional: name of workflow input this node checks (case-insensitive)",
            required=False,
        ),
    ]

    def __init__(self):
        self.validator = WorkflowValidator()

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        current_workflow = session_state.get("current_workflow", {"nodes": [], "edges": []})

        input_ref = args.get("input_ref")
        error = input_ref_error(input_ref, session_state)
        if error:
            return {
                "success": False,
                "error": error,
                "error_code": "INPUT_NOT_FOUND",
            }

        node_id = args.get("node_id")
        updates = {k: v for k, v in args.items() if k != "node_id" and v is not None}

        node_idx = next(
            (i for i, n in enumerate(current_workflow.get("nodes", [])) if n["id"] == node_id),
            None,
        )

        if node_idx is None:
            return {
                "success": False,
                "error": f"Node not found: {node_id}",
                "error_code": "NODE_NOT_FOUND",
            }

        inputs = session_state.get("workflow_analysis", {}).get("inputs", [])
        new_workflow = {
            "nodes": [dict(n) for n in current_workflow.get("nodes", [])],
            "edges": current_workflow.get("edges", []),
            "inputs": inputs,
        }
        new_workflow["nodes"][node_idx].update(updates)

        is_valid, errors = self.validator.validate(new_workflow, strict=False)
        if not is_valid:
            return {
                "success": False,
                "error": self.validator.format_errors(errors),
                "error_code": "VALIDATION_FAILED",
            }

        updated_node = new_workflow["nodes"][node_idx]
        return {
            "success": True,
            "action": "modify_node",
            "node": updated_node,
            "message": f"Updated node {node_id}",
        }
