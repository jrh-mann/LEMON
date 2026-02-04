"""Delete connection tool.

Multi-workflow architecture:
- Requires workflow_id parameter (workflow must exist in library)
- Loads workflow from database at start
- Auto-saves changes back to database when done
"""

from __future__ import annotations

from typing import Any, Dict

from ...validation.workflow_validator import WorkflowValidator
from ..core import Tool, ToolParameter
from .helpers import resolve_node_id, load_workflow_for_tool, save_workflow_changes


class DeleteConnectionTool(Tool):
    """Remove an edge from the workflow."""

    name = "delete_connection"
    description = "Remove a connection between two nodes. Requires workflow_id."
    parameters = [
        ToolParameter(
            "workflow_id",
            "string",
            "ID of the workflow containing the connection (from create_workflow)",
            required=True,
        ),
        ToolParameter("from_node_id", "string", "Source node ID", required=True),
        ToolParameter("to_node_id", "string", "Target node ID", required=True),
    ]

    def __init__(self):
        self.validator = WorkflowValidator()

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        workflow_id = args.get("workflow_id")
        
        # Load workflow from database
        workflow_data, error = load_workflow_for_tool(workflow_id, session_state)
        if error:
            return error
        # Use the workflow_id from loaded data (handles fallback to current_workflow_id)
        workflow_id = workflow_data["workflow_id"]
        
        # Extract workflow components
        nodes = workflow_data["nodes"]
        edges = workflow_data["edges"]
        variables = workflow_data["variables"]

        try:
            from_id = resolve_node_id(args.get("from_node_id"), nodes)
            to_id = resolve_node_id(args.get("to_node_id"), nodes)
        except ValueError as exc:
            return {"success": False, "error": str(exc), "error_code": "NODE_NOT_FOUND"}
        
        edge_id = f"{from_id}->{to_id}"

        # Create new edges list with the edge removed
        new_edges = [
            e for e in edges
            if not (e["from"] == from_id and e["to"] == to_id)
        ]
        
        new_workflow = {
            "nodes": nodes,
            "edges": new_edges,
            "variables": variables,
        }

        is_valid, errors = self.validator.validate(new_workflow, strict=False)
        if not is_valid:
            return {
                "success": False,
                "error": self.validator.format_errors(errors),
                "error_code": "VALIDATION_FAILED",
            }

        # Auto-save changes to database
        save_error = save_workflow_changes(workflow_id, session_state, edges=new_edges)
        if save_error:
            return save_error

        return {
            "success": True,
            "workflow_id": workflow_id,
            "action": "delete_connection",
            "edge_id": edge_id,
            "from_node_id": from_id,
            "to_node_id": to_id,
            "message": f"Removed connection from {from_id} to {to_id} in workflow {workflow_id}",
        }
