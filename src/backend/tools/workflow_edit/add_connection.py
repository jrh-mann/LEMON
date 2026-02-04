"""Add connection tool.

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


class AddConnectionTool(Tool):
    """Connect two nodes with an edge."""

    name = "add_connection"
    description = "Create an edge connecting two nodes. Requires workflow_id."
    parameters = [
        ToolParameter(
            "workflow_id",
            "string",
            "ID of the workflow to add the connection to (from create_workflow)",
            required=True,
        ),
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
        
        label = args.get("label", "")
        
        # Enforce and auto-assign edge labels for decision nodes
        # Decision node branches MUST have "true" or "false" labels for execution to work correctly
        source_node = next((n for n in nodes if n.get("id") == from_id), None)
        if source_node and source_node.get("type") == "decision":
            # Count existing edges from this decision node
            existing_edges_from_decision = [
                e for e in edges 
                if (e.get("from") or e.get("source")) == from_id
            ]
            existing_labels = {
                e.get("label", "").lower() 
                for e in existing_edges_from_decision
            }
            
            # Validate or auto-assign label
            if label:
                # Enforce that label must be "true" or "false"
                if label.lower() not in ("true", "false"):
                    return {
                        "success": False,
                        "error": f"Decision node edges must have label 'true' or 'false', got: '{label}'",
                        "error_code": "INVALID_EDGE_LABEL",
                    }
                label = label.lower()  # Normalize to lowercase
                
                # Prevent duplicate labels
                if label in existing_labels:
                    return {
                        "success": False,
                        "error": f"Decision node '{source_node.get('label', from_id)}' already has a '{label}' branch",
                        "error_code": "DUPLICATE_EDGE_LABEL",
                    }
            else:
                # Auto-assign "true" for first edge, "false" for second
                if "true" not in existing_labels:
                    label = "true"
                elif "false" not in existing_labels:
                    label = "false"
                else:
                    return {
                        "success": False,
                        "error": f"Decision node '{source_node.get('label', from_id)}' already has both true and false branches",
                        "error_code": "MAX_BRANCHES_REACHED",
                    }
        
        edge_id = f"{from_id}->{to_id}"

        new_edge = {
            "id": edge_id,
            "from": from_id,
            "to": to_id,
            "label": label,
        }

        # Create new edges list with the new edge
        new_edges = [*edges, new_edge]
        
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
            "action": "add_connection",
            "edge": new_edge,
            "message": f"Connected {from_id} to {to_id} in workflow {workflow_id}",
        }
