"""Modify node tool.

Multi-workflow architecture:
- Requires workflow_id parameter (workflow must exist in library)
- Loads workflow from database at start
- Auto-saves changes back to database when done
"""

from __future__ import annotations

from typing import Any, Dict

from ...validation.workflow_validator import WorkflowValidator
from ..core import Tool, ToolParameter
from .helpers import (
    resolve_node_id,
    validate_subprocess_node,
    load_workflow_for_tool,
    save_workflow_changes,
)
from .add_node import validate_decision_condition


class ModifyNodeTool(Tool):
    """Modify an existing node's properties.
    
    For decision nodes, you can update the 'condition' field with a structured
    condition object containing input_id, comparator, value, and optionally value2.
    """

    name = "modify_node"
    description = "Update an existing node's label, type, position, or condition. Requires workflow_id."
    parameters = [
        ToolParameter(
            "workflow_id",
            "string",
            "ID of the workflow containing the node (from create_workflow)",
            required=True,
        ),
        ToolParameter("node_id", "string", "ID of the node to modify", required=True),
        ToolParameter("label", "string", "New label text", required=False),
        ToolParameter("type", "string", "New node type", required=False),
        ToolParameter("x", "number", "New X coordinate", required=False),
        ToolParameter("y", "number", "New Y coordinate", required=False),
        # Decision node condition
        ToolParameter(
            "condition",
            "object",
            (
                "For decision nodes: Structured condition to evaluate. "
                "Object with: input_id (string), comparator (string), value (any), value2 (optional for ranges). "
                "Comparators by type: "
                "int/float: eq,neq,lt,lte,gt,gte,within_range | "
                "bool: is_true,is_false | "
                "string: str_eq,str_neq,str_contains,str_starts_with,str_ends_with | "
                "date: date_eq,date_before,date_after,date_between | "
                "enum: enum_eq,enum_neq"
            ),
            required=False,
        ),
        ToolParameter(
            "output_type",
            "string",
            "Optional: data type for output nodes (string, int, bool, json, file)",
            required=False,
        ),
        ToolParameter(
            "output_template",
            "string",
            "Optional: python f-string template for output (e.g., 'Result: {value}')",
            required=False,
        ),
        ToolParameter(
            "output_value",
            "any",
            "Optional: static value to return",
            required=False,
        ),
        # Subprocess-specific parameters
        ToolParameter(
            "subworkflow_id",
            "string",
            "For subprocess: ID of the workflow to call as a subflow",
            required=False,
        ),
        ToolParameter(
            "input_mapping",
            "object",
            "For subprocess: dict mapping parent input names to subworkflow input names",
            required=False,
        ),
        ToolParameter(
            "output_variable",
            "string",
            "For subprocess: name for the variable that stores subworkflow output",
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
        
        # Extract workflow components
        nodes = workflow_data["nodes"]
        edges = workflow_data["edges"]
        variables = workflow_data["variables"]

        raw_id = args.get("node_id")
        try:
            node_id = resolve_node_id(raw_id, nodes)
        except ValueError as exc:
            return {"success": False, "error": str(exc), "error_code": "NODE_NOT_FOUND"}

        # Build updates dict (exclude workflow_id and node_id)
        updates = {
            k: v for k, v in args.items() 
            if k not in ("workflow_id", "node_id") and v is not None
        }

        node_idx = next(
            (i for i, n in enumerate(nodes) if n["id"] == node_id),
            None,
        )

        if node_idx is None:
            return {
                "success": False,
                "error": f"Node not found: {node_id}",
                "error_code": "NODE_NOT_FOUND",
            }

        # Create new workflow state with updates
        new_nodes = [dict(n) for n in nodes]
        new_nodes[node_idx].update(updates)
        
        new_workflow = {
            "nodes": new_nodes,
            "edges": edges,
            "variables": variables,
        }

        # Validate subprocess configuration if node is/becomes a subprocess
        updated_node = new_nodes[node_idx]
        
        # Validate condition for decision nodes
        if updated_node.get("type") == "decision":
            condition = updated_node.get("condition")
            if condition:
                condition_error = validate_decision_condition(condition, variables)
                if condition_error:
                    return {
                        "success": False,
                        "error": condition_error,
                        "error_code": "INVALID_CONDITION",
                    }
        
        if updated_node.get("type") == "subprocess":
            # Build mock session for validation
            mock_session = {
                **session_state,
                "workflow_analysis": {"variables": variables},
            }
            subprocess_errors = validate_subprocess_node(
                updated_node,
                mock_session,
                check_workflow_exists=True,
            )
            if subprocess_errors:
                return {
                    "success": False,
                    "error": "\n".join(subprocess_errors),
                    "error_code": "SUBPROCESS_VALIDATION_FAILED",
                }

        is_valid, errors = self.validator.validate(new_workflow, strict=False)
        if not is_valid:
            return {
                "success": False,
                "error": self.validator.format_errors(errors),
                "error_code": "VALIDATION_FAILED",
            }

        # Auto-save changes to database
        save_error = save_workflow_changes(workflow_id, session_state, nodes=new_nodes)
        if save_error:
            return save_error

        return {
            "success": True,
            "workflow_id": workflow_id,
            "action": "modify_node",
            "node": updated_node,
            "message": f"Updated node {node_id} in workflow {workflow_id}",
        }
