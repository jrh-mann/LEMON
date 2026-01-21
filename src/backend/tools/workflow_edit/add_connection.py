"""Add connection tool."""

from __future__ import annotations

from typing import Any, Dict

from ...validation.workflow_validator import WorkflowValidator
from ..core import Tool, ToolParameter


class AddConnectionTool(Tool):
    """Connect two nodes with an edge."""

    name = "add_connection"
    description = "Create an edge connecting two nodes."
    parameters = [
        ToolParameter("from_node_id", "string", "Source node ID", required=True),
        ToolParameter("to_node_id", "string", "Target node ID", required=True),
        ToolParameter(
            "label",
            "string",
            "Edge label (e.g., 'true', 'false', or empty)",
            required=False,
        ),
    ]

    def __init__(self):
        self.validator = WorkflowValidator()

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        current_workflow = session_state.get("current_workflow", {"nodes": [], "edges": []})

        from_id = args.get("from_node_id")
        to_id = args.get("to_node_id")
        label = args.get("label", "")
        edge_id = f"{from_id}->{to_id}"

        new_edge = {
            "id": edge_id,
            "from": from_id,
            "to": to_id,
            "label": label,
        }

        new_workflow = {
            "nodes": current_workflow.get("nodes", []),
            "edges": [*current_workflow.get("edges", []), new_edge],
        }

        is_valid, errors = self.validator.validate(new_workflow, strict=False)
        if not is_valid:
            return {
                "success": False,
                "error": self.validator.format_errors(errors),
                "error_code": "VALIDATION_FAILED",
            }

        return {
            "success": True,
            "action": "add_connection",
            "edge": new_edge,
            "message": f"Connected {from_id} to {to_id}",
        }
