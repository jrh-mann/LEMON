"""Delete connection tool."""

from __future__ import annotations

from typing import Any, Dict

from ...validation.workflow_validator import WorkflowValidator
from ..core import Tool, ToolParameter


class DeleteConnectionTool(Tool):
    """Remove an edge from the workflow."""

    name = "delete_connection"
    description = "Remove a connection between two nodes."
    parameters = [
        ToolParameter("from_node_id", "string", "Source node ID", required=True),
        ToolParameter("to_node_id", "string", "Target node ID", required=True),
    ]

    def __init__(self):
        self.validator = WorkflowValidator()

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        current_workflow = session_state.get("current_workflow", {"nodes": [], "edges": []})

        # Get variables for validation of output templates
        workflow_analysis = session_state.get("workflow_analysis", {})
        variables = workflow_analysis.get("variables", [])

        from_id = args.get("from_node_id")
        to_id = args.get("to_node_id")
        edge_id = f"{from_id}->{to_id}"

        new_workflow = {
            "nodes": current_workflow.get("nodes", []),
            "edges": [
                e
                for e in current_workflow.get("edges", [])
                if not (e["from"] == from_id and e["to"] == to_id)
            ],
            "variables": variables,
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
            "action": "delete_connection",
            "edge_id": edge_id,
            "message": f"Removed connection from {from_id} to {to_id}",
        }
