"""Add connection tool.

Multi-workflow architecture:
- Uses current_workflow_id from session_state (implicit binding)
- Loads workflow from database at start
- Auto-saves changes back to database when done
"""

from __future__ import annotations

from typing import Any, Dict

from ..core import WorkflowTool, ToolParameter, tool_error
from .helpers import resolve_node_id, save_workflow_changes


class AddConnectionTool(WorkflowTool):
    """Connect two nodes with an edge."""

    name = "add_connection"
    description = (
        "Create an edge connecting two nodes in the active workflow. For decision nodes, use label "
        "'true' or 'false'. "
        "Validates that the connection creates a valid workflow."
    )
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

        try:
            from_id = resolve_node_id(args.get("from_node_id"), nodes)
            to_id = resolve_node_id(args.get("to_node_id"), nodes)
        except ValueError as exc:
            return tool_error(str(exc), "NODE_NOT_FOUND")
        
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
                    return tool_error(
                        f"Decision node edges must have label 'true' or 'false', got: '{label}'",
                        "INVALID_EDGE_LABEL",
                    )
                label = label.lower()  # Normalize to lowercase
                
                # Prevent duplicate labels
                if label in existing_labels:
                    return tool_error(
                        f"Decision node '{source_node.get('label', from_id)}' already has a '{label}' branch",
                        "DUPLICATE_EDGE_LABEL",
                    )
            else:
                # Auto-assign label based on target node position relative to existing sibling
                # Convention: left target = false, right target = true
                
                # If both labels are already taken, reject (max 2 branches)
                if "true" in existing_labels and "false" in existing_labels:
                    return tool_error(
                        f"Decision node '{source_node.get('label', from_id)}' already has both true and false branches",
                        "MAX_BRANCHES_REACHED",
                    )
                
                # If this is the first edge, we can't compare positions yet - use "true" as default
                if not existing_edges_from_decision:
                    label = "true"
                else:
                    # Second edge - compare target node x positions
                    target_node = next((n for n in nodes if n.get("id") == to_id), None)
                    
                    # Get the existing edge's target node
                    existing_edge = existing_edges_from_decision[0]
                    existing_target_id = existing_edge.get("to") or existing_edge.get("target")
                    existing_target_node = next((n for n in nodes if n.get("id") == existing_target_id), None)
                    
                    if target_node and existing_target_node:
                        target_x = target_node.get("x", 0)
                        existing_x = existing_target_node.get("x", 0)
                        
                        # Left (smaller x) = false, Right (larger x) = true
                        if target_x < existing_x:
                            # New target is to the left of existing
                            label = "false"
                        else:
                            # New target is to the right of existing
                            label = "true"
                        
                        # Check if this conflicts with existing label, swap if needed
                        existing_label = existing_edge.get("label", "").lower()
                        if label == existing_label:
                            # Swap the existing edge's label to maintain consistency
                            swapped_label = "false" if existing_label == "true" else "true"
                            for e in edges:
                                if (e.get("from") or e.get("source")) == from_id and (e.get("to") or e.get("target")) == existing_target_id:
                                    e["label"] = swapped_label
                                    break
                    else:
                        # Fallback: assign remaining label
                        if "true" not in existing_labels:
                            label = "true"
                        else:
                            label = "false"
        
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
            return tool_error(self.validator.format_errors(errors), "VALIDATION_FAILED")

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
