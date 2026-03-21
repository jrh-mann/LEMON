"""Modify node tool.

Multi-workflow architecture:
- Uses current_workflow_id from session_state (implicit binding)
- Loads workflow from database at start
- Auto-saves changes back to database when done
"""

from __future__ import annotations

from typing import Any, Dict

from ..core import WorkflowTool, ToolParameter
from .helpers import (
    resolve_node_id,
    save_workflow_changes,
    build_modified_node,
)


class ModifyNodeTool(WorkflowTool):
    """Modify an existing node's properties.

    For decision nodes, you can update the 'condition' field with a structured
    condition object containing variable (name), comparator, value, and optionally value2.

    For calculation nodes, you can update the 'calculation' field with output,
    operator, and operands.
    """

    name = "modify_node"
    description = (
        "Update an existing node's properties (label, type, position) in the active workflow. "
        "You must know the node_id first - call get_current_workflow to find it.\n\n"
        "For SUBPROCESS nodes: You can update subworkflow_id, input_mapping, and output_variable.\n"
        "For DECISION nodes: You can update the condition.\n"
        "For CALCULATION nodes: You can update the calculation definition."
    )
    parameters = [
        ToolParameter("node_id", "string", "ID of the node to modify", required=True),
        ToolParameter("label", "string", "New label text", required=False),
        ToolParameter("type", "string", "New node type", required=False,
                      enum=["start", "process", "decision", "subprocess", "calculation", "end"]),
        ToolParameter("x", "number", "New X coordinate", required=False),
        ToolParameter("y", "number", "New Y coordinate", required=False),
        ToolParameter("output_type", "string", "For 'end' nodes: data type of the output. Use 'number' for all numeric values.",
                      required=False, enum=["string", "number", "bool", "json"]),
        ToolParameter("output", "any",
                      "For 'end' nodes: what to return. variable name, template with {vars}, or literal value.",
                      required=False),
        ToolParameter("condition", "object", "For 'decision' nodes: condition. See add_node for schema details.", required=False),
        ToolParameter("calculation", "object", "For 'calculation' nodes: Updated calculation definition. See add_node for schema.", required=False),
        ToolParameter("subworkflow_id", "string", "For 'subprocess' nodes: ID of the workflow to call.", required=False),
        ToolParameter("input_mapping", "object", "For 'subprocess' nodes: Maps parent input names to subworkflow input names.", required=False),
        ToolParameter("output_variable", "string", "For 'subprocess' nodes only: Name for the variable that stores the subworkflow's output.", required=False),
    ]

    # Full JSON Schema override — condition and calculation have deeply nested schemas.
    _schema_override = {
        "type": "object",
        "properties": {
            "node_id": {
                "type": "string",
                "description": "ID of the node to modify",
            },
            "label": {
                "type": "string",
                "description": "New label text",
            },
            "type": {
                "type": "string",
                "enum": ["start", "process", "decision", "subprocess", "calculation", "end"],
                "description": "New node type",
            },
            "x": {"type": "number", "description": "New X coordinate"},
            "y": {"type": "number", "description": "New Y coordinate"},
            "output_type": {
                "type": "string",
                "enum": ["string", "number", "bool", "json"],
                "description": "For 'end' nodes: data type of the output. Use 'number' for all numeric values.",
            },
            "output": {
                "description": (
                    "For 'end' nodes: what to return. Smart routing: "
                    "variable name (e.g., 'BMI') returns that variable's typed value; "
                    "template with {vars} (e.g., 'Your BMI is {BMI}') does string interpolation; "
                    "literal value (e.g., 42, true) returns a static value."
                ),
            },
            "condition": {
                "description": (
                    "For 'decision' nodes: Simple or compound condition. "
                    "See add_node for full schema details."
                ),
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {
                            "variable": {"type": "string"},
                            "comparator": {"type": "string"},
                            "value": {"description": "Comparison value", "anyOf": [{"type": "string"}, {"type": "number"}, {"type": "boolean"}]},
                            "value2": {"description": "Second value (for 'between' comparator)", "anyOf": [{"type": "string"}, {"type": "number"}, {"type": "boolean"}]},
                        },
                        "required": ["variable", "comparator"],
                    },
                    {
                        "type": "object",
                        "properties": {
                            "operator": {"type": "string", "enum": ["and", "or"]},
                            "conditions": {"type": "array", "minItems": 2},
                        },
                        "required": ["operator", "conditions"],
                    },
                ],
            },
            "subworkflow_id": {
                "type": "string",
                "description": "For 'subprocess' nodes: ID of the workflow to call.",
            },
            "input_mapping": {
                "type": "object",
                "description": "For 'subprocess' nodes: Maps parent input names to subworkflow input names.",
                "additionalProperties": {"type": "string"},
            },
            "output_variable": {
                "type": "string",
                "description": "For 'subprocess' nodes only: Name for the variable that stores the subworkflow's output.",
            },
            "calculation": {
                "type": "object",
                "description": "For 'calculation' nodes: Updated calculation definition. See add_node for schema.",
            },
        },
        "required": ["node_id"],
    }

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

        new_nodes = [dict(n) for n in nodes]
        updated_node, added_variables, removed_variable_ids, build_error = build_modified_node(
            new_nodes[node_idx],
            updates,
            variables,
            session_state,
        )
        if build_error:
            return {
                "success": False,
                "error": build_error,
                "error_code": "INVALID_NODE_UPDATE",
            }
        new_nodes[node_idx] = updated_node
        
        new_workflow = {
            "nodes": new_nodes,
            "edges": edges,
            "variables": variables,
        }

        is_valid, errors = self.validator.validate(new_workflow, strict=False)
        if not is_valid:
            return {
                "success": False,
                "error": self.validator.format_errors(errors),
                "error_code": "VALIDATION_FAILED",
            }

        removed_variable_id_set = set(removed_variable_ids)
        new_variables = [
            v for v in variables if v.get("id") not in removed_variable_id_set
        ] + added_variables

        # Auto-save changes to database (include variables if they changed)
        save_kwargs = {"nodes": new_nodes}
        if removed_variable_ids or added_variables:
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
