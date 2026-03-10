"""Batch edit workflow tool.

Multi-workflow architecture:
- Uses current_workflow_id from session_state (implicit binding)
- Loads workflow from database at start
- Auto-saves changes back to database when done
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..core import WorkflowTool, ToolParameter
from .helpers import (
    build_new_node,
    build_modified_node,
    resolve_node_id,
    save_workflow_changes,
)


ALLOWED_MODIFY_NODE_FIELDS = {
    "label",
    "type",
    "x",
    "y",
    "condition",
    "calculation",
    "output_type",
    "output",
    "output_template",
    "output_variable",
    "output_value",
    "subworkflow_id",
    "input_mapping",
    "color",
}


class BatchEditWorkflowTool(WorkflowTool):
    """Apply multiple workflow changes atomically.

    Uses the current workflow from session state.
    """

    name = "batch_edit_workflow"
    description = (
        "Apply multiple changes to the active workflow in a single atomic operation. "
        "All changes are validated together - if any fail, none are applied. "
        "\n\n"
        "PRIMARY USE CASE - Temporary ID References: "
        "When you need to create nodes and immediately connect them in the same operation, "
        "use temporary IDs (like 'temp_decision', 'temp_start') instead of real node IDs. "
        "The tool automatically maps temp IDs to real UUIDs and updates all references. "
        "\n\n"
        "Common scenarios: "
        "(1) Decision nodes with branches - create decision + 2 branch nodes + 2 connections atomically, "
        "(2) Node chains - create start->process->end with connections in one operation, "
        "(3) Complex multi-step changes that should succeed or fail together, "
        "(4) Subprocess nodes with their connections - create subprocess and connect it atomically."
    )
    parameters = [
        ToolParameter(
            "operations",
            "array",
            (
                "List of operations. Each operation is an object with 'op' field plus operation-specific fields.\n\n"
                "add_node: {op, type, label, id (temp ID for referencing), x, y, condition?, output_type?, output?, subworkflow_id?, input_mapping?, output_variable?, calculation?}\n"
                "modify_node: {op, node_id, label?, type?, x?, y?, condition?, output_type?, output?, subworkflow_id?, input_mapping?, output_variable?, calculation?}\n"
                "delete_node: {op, node_id}\n"
                "add_connection: {op, from (node_id or temp_id), to (node_id or temp_id), label}\n"
                "delete_connection: {op, from (node_id), to (node_id)}"
            ),
            required=True,
            items={
                "type": "object",
                "properties": {
                    "op": {
                        "type": "string",
                        "enum": [
                            "add_node",
                            "modify_node",
                            "delete_node",
                            "add_connection",
                            "delete_connection",
                        ],
                    },
                    "id": {"type": "string", "description": "Temp ID for new nodes (e.g., temp_1)"},
                    "type": {"type": "string", "enum": ["start", "process", "decision", "subprocess", "calculation", "end"]},
                    "label": {"type": "string"},
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "condition": {
                        "description": "For decision nodes: simple {variable, comparator, value} or compound {operator, conditions: [...]}",
                    },
                    "output_type": {"type": "string", "enum": ["string", "number", "bool", "json"]},
                    "output": {"description": "For end nodes: variable name, template with {vars}, or literal value"},
                    "subworkflow_id": {"type": "string", "description": "For subprocess: workflow ID to call"},
                    "input_mapping": {"type": "object", "description": "For subprocess: parent->subworkflow input mapping"},
                    "output_variable": {"type": "string", "description": "For subprocess only: name for output variable"},
                    "calculation": {"type": "object", "description": "For calculation nodes: {output, operator, operands} - see add_node for full schema"},
                    "node_id": {"type": "string", "description": "Existing node ID"},
                    "from": {"type": "string", "description": "Source node ID or temp ID"},
                    "to": {"type": "string", "description": "Target node ID or temp ID"},
                },
                "required": ["op"],
            },
        ),
    ]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        """
        Operations format:
        [
            {"op": "add_node", "type": "decision", "label": "Age check?", "id": "temp_1",
             "condition": {"variable": "Age", "comparator": "gte", "value": 18}},
            {"op": "add_connection", "from": "input_age", "to": "temp_1", "label": "true"},
            {"op": "modify_connection", "from": "temp_1", "to": "output_1", "label": "false"},
            {"op": "modify_node", "node_id": "node_abc", "label": "Updated label"},
            {"op": "delete_node", "node_id": "node_xyz"},
            {"op": "delete_connection", "from": "node_a", "to": "node_b"}
        ]

        Decision node edges MUST have labels "true" or "false". Labels are auto-assigned if not provided.
        Use modify_connection to change an existing edge's label.

        Temporary IDs: Use "temp_X" or any ID for new nodes. They'll be replaced with real UUIDs.
        """
        workflow_data, error = self._load_workflow(args, **kwargs)
        if error:
            return error
        workflow_id = workflow_data["workflow_id"]
        session_state = kwargs.get("session_state", {})

        operations = args.get("operations", [])
        if not isinstance(operations, list):
            return {"success": False, "error": "operations must be an array"}

        # Extract workflow components from loaded data
        nodes = [dict(n) for n in workflow_data["nodes"]]
        edges = [dict(e) for e in workflow_data["edges"]]
        variables = list(workflow_data["variables"])

        # Track what was modified for auto-save
        variables_modified = False

        temp_id_map: Dict[str, str] = {}
        applied_operations: List[Dict[str, Any]] = []

        try:
            for op in operations:
                op_type = op.get("op")

                if op_type == "add_node":
                    temp_id = op.get("id")

                    # Delegate node construction + validation to shared builder
                    # build_new_node generates a UUID-based node_id internally
                    new_node, new_vars, build_err = build_new_node(
                        params=op,
                        variables=variables,
                        session_state=session_state,
                    )
                    if build_err:
                        raise ValueError(build_err)

                    # Map temp ID to the real generated ID
                    real_id = new_node["id"]
                    if temp_id:
                        temp_id_map[temp_id] = real_id

                    # Append auto-registered variables
                    if new_vars:
                        variables.extend(new_vars)
                        variables_modified = True

                    nodes.append(new_node)
                    applied_operations.append({"op": "add_node", "node": new_node})

                elif op_type == "modify_node":
                    node_id = self._resolve_id(op["node_id"], temp_id_map, nodes)
                    node_idx = next(
                        (i for i, n in enumerate(nodes) if n["id"] == node_id),
                        None,
                    )
                    if node_idx is None:
                        raise ValueError(f"Node not found: {node_id}")

                    updates = {k: v for k, v in op.items() if k not in ["op", "node_id"]}
                    unknown_fields = sorted(set(updates) - ALLOWED_MODIFY_NODE_FIELDS)
                    if unknown_fields:
                        raise ValueError(
                            f"modify_node does not allow fields: {', '.join(unknown_fields)}"
                        )
                    updated_node, added_variables, removed_variable_ids, build_error = build_modified_node(
                        nodes[node_idx],
                        updates,
                        variables,
                        session_state,
                    )
                    if build_error:
                        raise ValueError(build_error)
                    nodes[node_idx] = updated_node
                    if removed_variable_ids:
                        removed_variable_id_set = set(removed_variable_ids)
                        variables = [
                            var for var in variables
                            if var.get("id") not in removed_variable_id_set
                        ]
                        variables_modified = True
                    if added_variables:
                        variables.extend(added_variables)
                        variables_modified = True
                    
                    applied_operations.append(
                        {"op": "modify_node", "node_id": node_id, "updates": updates}
                    )

                elif op_type == "delete_node":
                    node_id = self._resolve_id(op["node_id"], temp_id_map, nodes)
                    nodes = [n for n in nodes if n["id"] != node_id]
                    edges = [
                        e
                        for e in edges
                        if e["from"] != node_id and e["to"] != node_id
                    ]
                    # Clean up derived variables whose producing node is deleted
                    removed = [v for v in variables if v.get("source_node_id") == node_id]
                    if removed:
                        variables = [v for v in variables if v.get("source_node_id") != node_id]
                        variables_modified = True
                    applied_operations.append({"op": "delete_node", "node_id": node_id})

                elif op_type == "add_connection":
                    from_id = self._resolve_id(op["from"], temp_id_map, nodes)
                    to_id = self._resolve_id(op["to"], temp_id_map, nodes)
                    edge_id = f"{from_id}->{to_id}"
                    label = op.get("label", "")

                    # Auto-assign edge labels for decision nodes if not provided
                    # This ensures decision node branches are correctly identified during execution
                    source_node = next((n for n in nodes if n.get("id") == from_id), None)
                    if source_node and source_node.get("type") == "decision":
                        # Get existing edges from this decision node
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
                                raise ValueError(
                                    f"Decision node edges must have label 'true' or 'false', got: '{label}'"
                                )
                            label = label.lower()  # Normalize to lowercase
                        else:
                            # Auto-assign "true" for first edge, "false" for second
                            if "true" not in existing_labels:
                                label = "true"
                            elif "false" not in existing_labels:
                                label = "false"
                            else:
                                raise ValueError(
                                    f"Decision node '{source_node.get('label', from_id)}' already has both true and false branches"
                                )

                    new_edge = {
                        "id": edge_id,
                        "from": from_id,
                        "to": to_id,
                        "label": label,
                    }
                    edges.append(new_edge)
                    applied_operations.append({"op": "add_connection", "edge": new_edge})

                elif op_type == "delete_connection":
                    from_id = self._resolve_id(op["from"], temp_id_map, nodes)
                    to_id = self._resolve_id(op["to"], temp_id_map, nodes)
                    edge_id = f"{from_id}->{to_id}"

                    edges = [
                        e
                        for e in edges
                        if not (e["from"] == from_id and e["to"] == to_id)
                    ]
                    applied_operations.append({"op": "delete_connection", "edge_id": edge_id})

                elif op_type == "modify_connection":
                    # Modify an existing edge's label (primarily for decision node branches)
                    from_id = self._resolve_id(op["from"], temp_id_map, nodes)
                    to_id = self._resolve_id(op["to"], temp_id_map, nodes)
                    edge_id = f"{from_id}->{to_id}"
                    new_label = op.get("label", "")

                    # Find the edge to modify
                    edge_idx = next(
                        (i for i, e in enumerate(edges) if e["from"] == from_id and e["to"] == to_id),
                        None,
                    )
                    if edge_idx is None:
                        raise ValueError(f"Edge not found: {from_id} -> {to_id}")

                    # Validate label for decision nodes
                    source_node = next((n for n in nodes if n.get("id") == from_id), None)
                    if source_node and source_node.get("type") == "decision":
                        if new_label.lower() not in ("true", "false"):
                            raise ValueError(
                                f"Decision node edges must have label 'true' or 'false', got: '{new_label}'"
                            )
                        new_label = new_label.lower()  # Normalize to lowercase

                        # Ensure we're not duplicating a label
                        other_edges_from_decision = [
                            e for i, e in enumerate(edges)
                            if (e.get("from") or e.get("source")) == from_id and i != edge_idx
                        ]
                        existing_labels = {e.get("label", "").lower() for e in other_edges_from_decision}
                        if new_label in existing_labels:
                            raise ValueError(
                                f"Decision node '{source_node.get('label', from_id)}' already has a '{new_label}' branch"
                            )

                    # Update the edge
                    edges[edge_idx]["label"] = new_label
                    applied_operations.append({
                        "op": "modify_connection",
                        "edge_id": edge_id,
                        "new_label": new_label,
                    })

                else:
                    raise ValueError(f"Unknown operation type: {op_type}")

        except Exception as exc:
            return {"success": False, "error": f"Failed to apply operations: {str(exc)}"}

        # Validate the resulting workflow
        new_workflow = {
            "nodes": nodes,
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

        # Auto-save changes to database
        save_kwargs: Dict[str, Any] = {"nodes": nodes, "edges": edges}
        if variables_modified:
            save_kwargs["variables"] = variables
        
        save_error = save_workflow_changes(workflow_id, session_state, **save_kwargs)
        if save_error:
            return save_error

        # Build result with workflow state for orchestrator sync
        result: Dict[str, Any] = {
            "success": True,
            "workflow_id": workflow_id,
            "action": "batch_edit",
            "operations": applied_operations,
            "operation_count": len(applied_operations),
            "message": f"Applied {len(applied_operations)} operations to workflow {workflow_id}",
            # Include full workflow state for orchestrator to sync
            "workflow": {"nodes": nodes, "edges": edges},
        }
        
        # Include workflow_analysis if variables were modified
        if variables_modified:
            result["workflow_analysis"] = {"variables": variables}
        
        return result

    def _resolve_id(
        self,
        id_or_temp: str,
        temp_map: Dict[str, str],
        nodes: List[Dict[str, Any]] | None = None,
    ) -> str:
        """Resolve temp IDs, real IDs, or node labels to a real node ID."""
        # Temp ID takes priority (e.g. "temp_1" created earlier in the batch)
        if id_or_temp in temp_map:
            return temp_map[id_or_temp]
        # Fall back to label-or-ID resolution when nodes are available
        if nodes is not None:
            return resolve_node_id(id_or_temp, nodes)
        return id_or_temp
