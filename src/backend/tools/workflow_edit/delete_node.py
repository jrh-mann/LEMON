"""Delete node tool."""

from __future__ import annotations

from typing import Any, Dict

from ...validation.workflow_validator import WorkflowValidator
from ..core import Tool, ToolParameter
from .helpers import resolve_node_id


class DeleteNodeTool(Tool):
    """Delete a node from the workflow."""

    name = "delete_node"
    description = "Remove a node and all connected edges from the workflow."
    parameters = [
        ToolParameter("node_id", "string", "ID of the node to delete", required=True),
    ]

    def __init__(self):
        self.validator = WorkflowValidator()

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        current_workflow = session_state.get("current_workflow", {"nodes": [], "edges": []})

        # Get variables for validation of output templates
        workflow_analysis = session_state.get("workflow_analysis", {})
        variables = workflow_analysis.get("variables", [])

        raw_id = args.get("node_id")
        nodes = current_workflow.get("nodes", [])
        try:
            node_id = resolve_node_id(raw_id, nodes)
        except ValueError as exc:
            return {"success": False, "error": str(exc), "error_code": "NODE_NOT_FOUND"}

        new_workflow = {
            "nodes": [n for n in current_workflow.get("nodes", []) if n["id"] != node_id],
            "edges": [
                e
                for e in current_workflow.get("edges", [])
                if e["from"] != node_id and e["to"] != node_id
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
            "action": "delete_node",
            "node_id": node_id,
            "message": f"Deleted node {node_id} and connected edges",
        }
