"""Modify node tool.

Multi-workflow architecture:
- Requires workflow_id parameter (workflow must exist in library)
- Loads workflow from database at start
- Auto-saves changes back to database when done
"""

from __future__ import annotations

from typing import Any, Dict

from ..core import WorkflowTool, ToolParameter
from .helpers import (
    resolve_node_id,
    validate_subprocess_node,
    save_workflow_changes,
    derive_variables_for_node,
)
from .add_node import validate_decision_condition, validate_calculation


class ModifyNodeTool(WorkflowTool):
    """Modify an existing node's properties.
    
    For decision nodes, you can update the 'condition' field with a structured
    condition object containing input_id, comparator, value, and optionally value2.
    
    For calculation nodes, you can update the 'calculation' field with output,
    operator, and operands.
    """

    category = "workflow_edit"
    prompt_hint = "MODIFY/CHANGE/UPDATE/RENAME → call modify_node with workflow_id"

    name = "modify_node"
    description = "Update an existing node's label, type, position, condition, or calculation. Requires workflow_id."
    parameters = [
        ToolParameter(
            "workflow_id",
            "string",
            "ID of the workflow containing the node (from create_workflow)",
            required=True,
        ),
        ToolParameter("node_id", "string", "ID of the node to modify", required=True),
        ToolParameter("label", "string", "New label text", required=False),
        ToolParameter(
            "type",
            "string",
            "New node type",
            required=False,
            schema_override={
                "type": "string",
                "enum": ["start", "process", "decision", "subprocess", "calculation", "end"],
                "description": "New node type",
            },
        ),
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
            schema_override={
                "description": (
                    "For 'decision' nodes: Simple or compound condition. "
                    "See add_node for full schema details."
                ),
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {
                            "input_id": {"type": "string"},
                            "comparator": {"type": "string"},
                            "value": {},
                            "value2": {}
                        },
                        "required": ["input_id", "comparator"]
                    },
                    {
                        "type": "object",
                        "properties": {
                            "operator": {"type": "string", "enum": ["and", "or"]},
                            "conditions": {"type": "array", "minItems": 2}
                        },
                        "required": ["operator", "conditions"]
                    }
                ]
            },
        ),
        # Calculation node config
        ToolParameter(
            "calculation",
            "object",
            (
                "For calculation nodes: Mathematical operation to perform. "
                "Object with: output {name, description?}, operator (string), operands (array). "
                "Each operand is {kind: 'variable', ref: 'var_id'} or {kind: 'literal', value: number}."
            ),
            required=False,
            schema_override={
                "type": "object",
                "description": "For 'calculation' nodes: Updated calculation definition. See add_node for schema.",
            },
        ),
        ToolParameter(
            "output_type",
            "string",
            "Optional: data type for output nodes (string, int, bool, json, file)",
            required=False,
            schema_override={
                "type": "string",
                "enum": ["string", "number", "bool", "json"],
                "description": "For 'end' nodes: data type of the output. Use 'number' for all numeric values.",
            },
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
            schema_override={
                "type": "object",
                "description": "For 'subprocess' nodes: Maps parent input names to subworkflow input names.",
                "additionalProperties": {"type": "string"},
            },
        ),
        ToolParameter(
            "output_variable",
            "string",
            (
                "For 'end' nodes returning number/bool: Name of the variable to return (preserves type). "
                "For subprocess: name for the variable that stores subworkflow output."
            ),
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

        # Snapshot old node before mutation for derived-variable comparison
        old_node = dict(nodes[node_idx])

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
        
        # Validate calculation for calculation nodes
        if updated_node.get("type") == "calculation":
            calculation = updated_node.get("calculation")
            if calculation:
                calculation_error = validate_calculation(calculation, variables)
                if calculation_error:
                    return {
                        "success": False,
                        "error": calculation_error,
                        "error_code": "INVALID_CALCULATION",
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

        # ---------------------------------------------------------------
        # Derived variable lifecycle: compare old vs new derived vars
        # ---------------------------------------------------------------
        old_derived = derive_variables_for_node(old_node, variables, session_state)
        new_derived = derive_variables_for_node(updated_node, variables, session_state)

        old_derived_ids = {v["id"] for v in old_derived}
        new_derived_ids = {v["id"] for v in new_derived}

        # IDs to remove (were derived from old config, no longer apply)
        removed_variable_ids = list(old_derived_ids - new_derived_ids)
        # Variables to add (derived from new config, didn't exist before)
        added_variables = [v for v in new_derived if v["id"] not in old_derived_ids]

        # Apply to variables list: remove old, add new
        new_variables = [
            v for v in variables if v.get("id") not in old_derived_ids
        ] + new_derived

        # Auto-save changes to database (include variables if they changed)
        save_kwargs = {"nodes": new_nodes}
        if old_derived_ids != new_derived_ids:
            save_kwargs["variables"] = new_variables
        save_error = save_workflow_changes(workflow_id, session_state, **save_kwargs)
        if save_error:
            return save_error

        return {
            "success": True,
            "workflow_id": workflow_id,
            "action": "modify_node",
            "node": updated_node,
            "removed_variable_ids": removed_variable_ids,
            "new_variables": added_variables,
            "message": f"Updated node {node_id} in workflow {workflow_id}",
        }
