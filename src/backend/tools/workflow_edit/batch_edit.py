"""Batch edit workflow tool.

Multi-workflow architecture:
- Requires workflow_id parameter (workflow must exist in library)
- Loads workflow from database at start
- Auto-saves changes back to database when done
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List

from ...validation.workflow_validator import WorkflowValidator
from ..core import Tool, ToolParameter
from ..workflow_input.add import generate_variable_id
from ..workflow_input.helpers import normalize_variable_name
from .helpers import (
    get_node_color,
    resolve_node_id,
    validate_subprocess_node,
    load_workflow_for_tool,
    save_workflow_changes,
)
from .add_node import validate_decision_condition


class BatchEditWorkflowTool(Tool):
    """Apply multiple workflow changes atomically.
    
    Requires workflow_id - the workflow must exist in the library first
    (create it with create_workflow tool).
    """

    name = "batch_edit_workflow"
    description = """
    Apply multiple workflow changes in a single atomic operation.
    Requires workflow_id - workflow must exist in library first.
    Validation uses lenient mode - you can create decision nodes without branches, then add connections later.

    Use this for efficient bulk operations:
    - Add multiple nodes at once
    - Add node + connections together
    - Modify edge labels (e.g., set "true"/"false" on decision branches)
    - Complex multi-step changes

    DECISION NODE EDGES: Decision nodes MUST have exactly two outgoing edges with labels "true" and "false".
    When adding connections from decision nodes, use add_connection with label "true" or "false".
    To change an edge label, use modify_connection.

    For decision nodes, include a 'condition' object with: input_id, comparator, value, value2 (optional).
    Comparators by type:
    - int/float: eq, neq, lt, lte, gt, gte, within_range
    - bool: is_true, is_false
    - string: str_eq, str_neq, str_contains, str_starts_with, str_ends_with
    - date: date_eq, date_before, date_after, date_between
    - enum: enum_eq, enum_neq

    Example: Add decision with condition and both branches
    {
      "workflow_id": "wf_abc123",
      "operations": [
        {"op": "add_node", "type": "decision", "label": "Age >= 18?", "id": "temp_decision", "x": 100, "y": 100,
         "condition": {"input_id": "input_age_int", "comparator": "gte", "value": 18}},
        {"op": "add_node", "type": "end", "label": "Child", "id": "temp_child", "x": 50, "y": 200},
        {"op": "add_node", "type": "end", "label": "Adult", "id": "temp_adult", "x": 150, "y": 200},
        {"op": "add_connection", "from": "temp_decision", "to": "temp_child", "label": "false"},
        {"op": "add_connection", "from": "temp_decision", "to": "temp_adult", "label": "true"}
      ]
    }

    Example: Modify an edge label
    {"op": "modify_connection", "from": "node_abc", "to": "node_xyz", "label": "true"}
    """
    parameters = [
        # workflow_id is REQUIRED and must be first
        ToolParameter(
            "workflow_id",
            "string",
            "ID of the workflow to edit (from create_workflow)",
            required=True,
        ),
        ToolParameter(
            "operations",
            "array",
            "List of operations to perform. Each operation has 'op' and parameters.",
            required=True,
        ),
    ]

    def __init__(self):
        self.validator = WorkflowValidator()

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        """
        Operations format:
        [
            {"op": "add_node", "type": "decision", "label": "Age check?", "id": "temp_1",
             "condition": {"input_id": "input_age_int", "comparator": "gte", "value": 18}},
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
        session_state = kwargs.get("session_state", {})
        workflow_id = args.get("workflow_id")

        # Load workflow from database
        workflow_data, error = load_workflow_for_tool(workflow_id, session_state)
        if error:
            return error
        # Use the workflow_id from loaded data (handles fallback to current_workflow_id)
        workflow_id = workflow_data["workflow_id"]

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
                    real_id = f"node_{uuid.uuid4().hex[:8]}"
                    if temp_id:
                        temp_id_map[temp_id] = real_id

                    node_type = op["type"]
                    new_node = {
                        "id": real_id,
                        "type": node_type,
                        "label": op["label"],
                        "x": op.get("x", 0),
                        "y": op.get("y", 0),
                        "color": get_node_color(node_type),
                    }
                    
                    # Handle decision node condition (required for decision nodes)
                    condition = op.get("condition")
                    if node_type == "decision":
                        if not condition:
                            raise ValueError(
                                f"Decision node '{op['label']}' requires a 'condition' object. "
                                f"Provide: {{input_id: '<input_id>', comparator: '<comparator>', value: <value>}}"
                            )
                        condition_error = validate_decision_condition(condition, variables)
                        if condition_error:
                            raise ValueError(f"Invalid condition for decision node '{op['label']}': {condition_error}")
                        new_node["condition"] = condition
                    elif condition:
                        # Allow condition on other node types for future proofing / type changes
                        new_node["condition"] = condition
                    
                    # Add output configuration for 'end' nodes
                    if node_type == "end":
                        new_node["output_type"] = op.get("output_type", "string")
                        # For number/bool outputs, prefer output_variable over output_template
                        if op.get("output_variable"):
                            new_node["output_variable"] = op["output_variable"]
                        elif op.get("output_template"):
                            new_node["output_template"] = op["output_template"]
                        if op.get("output_value") is not None:
                            new_node["output_value"] = op["output_value"]
                    else:
                        if "output_type" in op:
                            new_node["output_type"] = op["output_type"]
                        if "output_variable" in op:
                            new_node["output_variable"] = op["output_variable"]
                        if "output_template" in op:
                            new_node["output_template"] = op["output_template"]
                        if "output_value" in op:
                            new_node["output_value"] = op["output_value"]

                    # Handle subprocess-specific fields
                    if node_type == "subprocess":
                        subworkflow_id = op.get("subworkflow_id")
                        input_mapping = op.get("input_mapping")
                        output_variable = op.get("output_variable")
                        
                        if subworkflow_id:
                            new_node["subworkflow_id"] = subworkflow_id
                        if input_mapping is not None:
                            new_node["input_mapping"] = input_mapping
                        if output_variable:
                            new_node["output_variable"] = output_variable
                            
                            # Auto-register output_variable as a workflow variable
                            existing_var_names = [
                                normalize_variable_name(v.get("name", ""))
                                for v in variables
                            ]
                            if normalize_variable_name(output_variable) not in existing_var_names:
                                # Generate variable ID with subprocess source
                                var_id = generate_variable_id(output_variable, "string", "subprocess")
                                new_variable = {
                                    "id": var_id,
                                    "name": output_variable,
                                    "type": "string",  # Default - ideally inferred from subworkflow
                                    "source": "subprocess",
                                    "source_node_id": real_id,
                                    "description": f"Output from subprocess '{op['label']}'",
                                }
                                variables.append(new_variable)
                                variables_modified = True
                        
                        # Validate subprocess node configuration
                        mock_session = {
                            **session_state,
                            "workflow_analysis": {"variables": variables},
                        }
                        subprocess_errors = validate_subprocess_node(
                            new_node,
                            mock_session,
                            check_workflow_exists=True,
                        )
                        if subprocess_errors:
                            raise ValueError("\n".join(subprocess_errors))
                    else:
                        # Still allow subprocess fields on other types (for type changes)
                        if "subworkflow_id" in op:
                            new_node["subworkflow_id"] = op["subworkflow_id"]
                        if "input_mapping" in op:
                            new_node["input_mapping"] = op["input_mapping"]
                        if "output_variable" in op:
                            new_node["output_variable"] = op["output_variable"]

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
                    nodes[node_idx].update(updates)
                    
                    # Validate condition if node is/becomes decision type
                    updated_node = nodes[node_idx]
                    if updated_node.get("type") == "decision":
                        condition = updated_node.get("condition")
                        if condition:
                            condition_error = validate_decision_condition(condition, variables)
                            if condition_error:
                                raise ValueError(f"Invalid condition for decision node: {condition_error}")
                    
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
