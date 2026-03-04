"""Delete node tool.

Multi-workflow architecture:
- Uses current_workflow_id from session_state (implicit binding)
- Loads workflow from database at start
- Auto-saves changes back to database when done
"""

from __future__ import annotations

from typing import Any, Dict

from ..core import WorkflowTool, ToolParameter
from .helpers import resolve_node_id, save_workflow_changes


class DeleteNodeTool(WorkflowTool):
    """Delete a node from the workflow."""

    name = "delete_node"
    description = "Remove a node and all connected edges from the workflow."
    parameters = [
        ToolParameter("node_id", "string", "ID of the node to delete", required=True),
    ]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        workflow_data, error = self._load_workflow(args, **kwargs)
        if error:
            return error
        workflow_id = workflow_data["workflow_id"]
        session_state = kwargs.get("session_state", {})
        
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
        
        # Remove derived variables whose producing node is being deleted
        removed_variable_ids = [
            v["id"] for v in variables
            if v.get("source_node_id") == node_id
        ]
        new_variables = [
            v for v in variables
            if v.get("source_node_id") != node_id
        ]

        new_workflow = {
            "nodes": new_nodes,
            "edges": new_edges,
            "variables": new_variables,
        }

        is_valid, errors = self.validator.validate(new_workflow, strict=False)
        if not is_valid:
            return {
                "success": False,
                "error": self.validator.format_errors(errors),
                "error_code": "VALIDATION_FAILED",
            }

        # Auto-save changes to database
        save_kwargs = {"nodes": new_nodes, "edges": new_edges}
        if removed_variable_ids:
            save_kwargs["variables"] = new_variables
        save_error = save_workflow_changes(workflow_id, session_state, **save_kwargs)
        if save_error:
            return save_error

        return {
            "success": True,
            "workflow_id": workflow_id,
            "action": "delete_node",
            "node_id": node_id,
            "removed_variable_ids": removed_variable_ids,
            "message": f"Deleted node {node_id} and connected edges from workflow {workflow_id}",
        }
