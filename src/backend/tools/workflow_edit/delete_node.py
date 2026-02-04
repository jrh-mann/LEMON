"""Delete node tool.

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


class DeleteNodeTool(Tool):
    """Delete a node from the workflow."""

    name = "delete_node"
    description = "Remove a node and all connected edges from the workflow. Requires workflow_id."
    parameters = [
        ToolParameter(
            "workflow_id",
            "string",
            "ID of the workflow containing the node (from create_workflow)",
            required=True,
        ),
        ToolParameter("node_id", "string", "ID of the node to delete", required=True),
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

        raw_id = args.get("node_id")
        try:
            node_id = resolve_node_id(raw_id, nodes)
        except ValueError as exc:
            return {"success": False, "error": str(exc), "error_code": "NODE_NOT_FOUND"}

        # Create new workflow state with node and connected edges removed
        new_nodes = [n for n in nodes if n["id"] != node_id]
        new_edges = [
            e for e in edges
            if e["from"] != node_id and e["to"] != node_id
        ]
        
        new_workflow = {
            "nodes": new_nodes,
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
        save_error = save_workflow_changes(
            workflow_id, session_state, 
            nodes=new_nodes, 
            edges=new_edges
        )
        if save_error:
            return save_error

        return {
            "success": True,
            "workflow_id": workflow_id,
            "action": "delete_node",
            "node_id": node_id,
            "message": f"Deleted node {node_id} and connected edges from workflow {workflow_id}",
        }
