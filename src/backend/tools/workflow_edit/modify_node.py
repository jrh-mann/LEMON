"""Modify node tool."""

from __future__ import annotations

from typing import Any, Dict

from ...validation.workflow_validator import WorkflowValidator
from ..core import Tool, ToolParameter
from .helpers import resolve_node_id, validate_subprocess_node
from .add_node import validate_decision_condition


class ModifyNodeTool(Tool):
    """Modify an existing node's properties.
    
    For decision nodes, you can update the 'condition' field with a structured
    condition object containing input_id, comparator, value, and optionally value2.
    """

    name = "modify_node"
    description = "Update an existing node's label, type, position, or condition."
    parameters = [
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
        current_workflow = session_state.get("current_workflow", {"nodes": [], "edges": []})

        raw_id = args.get("node_id")
        nodes = current_workflow.get("nodes", [])
        try:
            node_id = resolve_node_id(raw_id, nodes)
        except ValueError as exc:
            return {"success": False, "error": str(exc), "error_code": "NODE_NOT_FOUND"}

        updates = {k: v for k, v in args.items() if k != "node_id" and v is not None}

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

        # Get variables for validation
        workflow_analysis = session_state.get("workflow_analysis", {})
        variables = workflow_analysis.get("variables", [])
        
        new_workflow = {
            "nodes": [dict(n) for n in current_workflow.get("nodes", [])],
            "edges": current_workflow.get("edges", []),
            "variables": variables,
        }
        new_workflow["nodes"][node_idx].update(updates)

        # Validate subprocess configuration if node is/becomes a subprocess
        updated_node = new_workflow["nodes"][node_idx]
        
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
            subprocess_errors = validate_subprocess_node(
                updated_node,
                session_state,
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

        updated_node = new_workflow["nodes"][node_idx]
        return {
            "success": True,
            "action": "modify_node",
            "node": updated_node,
            "message": f"Updated node {node_id}",
        }
