"""Batch edit workflow tool."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List

from ...validation.workflow_validator import WorkflowValidator
from ..core import Tool, ToolParameter
from .helpers import get_node_color, input_ref_error, validate_subprocess_node


class BatchEditWorkflowTool(Tool):
    """Apply multiple workflow changes atomically."""

    name = "batch_edit_workflow"
    description = """
    Apply multiple workflow changes in a single atomic operation.
    Validation uses lenient mode - you can create decision nodes without branches, then add connections later.

    Use this for efficient bulk operations:
    - Add multiple nodes at once
    - Add node + connections together
    - Complex multi-step changes

    Example: Add decision with both branches
    {
      "operations": [
        {"op": "add_node", "type": "decision", "label": "Age check?", "id": "temp_decision", "x": 100, "y": 100},
        {"op": "add_node", "type": "end", "label": "Child", "id": "temp_child", "x": 50, "y": 200},
        {"op": "add_node", "type": "end", "label": "Adult", "id": "temp_adult", "x": 150, "y": 200},
        {"op": "add_connection", "from": "temp_decision", "to": "temp_child", "label": "true"},
        {"op": "add_connection", "from": "temp_decision", "to": "temp_adult", "label": "false"}
      ]
    }
    """
    parameters = [
        ToolParameter(
            "operations",
            "array",
            "List of operations to perform. Each operation has 'op' and parameters.",
            required=True,
        )
    ]

    def __init__(self):
        self.validator = WorkflowValidator()

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        """
        Operations format:
        [
            {"op": "add_node", "type": "decision", "label": "Age check?", "id": "temp_1"},
            {"op": "add_connection", "from": "input_age", "to": "temp_1", "label": ""},
            {"op": "add_connection", "from": "temp_1", "to": "output_1", "label": "true"},
            {"op": "modify_node", "node_id": "node_abc", "label": "Updated label"},
            {"op": "delete_node", "node_id": "node_xyz"},
            {"op": "delete_connection", "from": "node_a", "to": "node_b"}
        ]

        Temporary IDs: Use "temp_X" or any ID for new nodes. They'll be replaced with real UUIDs.
        """
        session_state = kwargs.get("session_state", {})
        current_workflow = session_state.get("current_workflow", {"nodes": [], "edges": []})

        operations = args.get("operations", [])
        if not isinstance(operations, list):
            return {"success": False, "error": "operations must be an array"}

        inputs = session_state.get("workflow_analysis", {}).get("inputs", [])
        new_workflow = {
            "nodes": [dict(n) for n in current_workflow.get("nodes", [])],
            "edges": [dict(e) for e in current_workflow.get("edges", [])],
            "inputs": inputs,
        }

        temp_id_map: Dict[str, str] = {}
        applied_operations: List[Dict[str, Any]] = []

        try:
            for op in operations:
                op_type = op.get("op")

                if op_type == "add_node":
                    input_ref = op.get("input_ref")
                    error = input_ref_error(input_ref, session_state)
                    if error:
                        raise ValueError(error)

                    temp_id = op.get("id")
                    real_id = f"node_{uuid.uuid4().hex[:8]}"
                    if temp_id:
                        temp_id_map[temp_id] = real_id

                    new_node = {
                        "id": real_id,
                        "type": op["type"],
                        "label": op["label"],
                        "x": op.get("x", 0),
                        "y": op.get("y", 0),
                        "color": get_node_color(op["type"]),
                    }

                    if input_ref:
                        new_node["input_ref"] = input_ref
                    
                    # Add output configuration for 'end' nodes
                    if op["type"] == "end":
                        new_node["output_type"] = op.get("output_type", "string")
                        new_node["output_template"] = op.get("output_template", "")
                        new_node["output_value"] = op.get("output_value", None)
                    else:
                        if "output_type" in op:
                            new_node["output_type"] = op["output_type"]
                        if "output_template" in op:
                            new_node["output_template"] = op["output_template"]
                        if "output_value" in op:
                            new_node["output_value"] = op["output_value"]

                    # Handle subprocess-specific fields
                    if op["type"] == "subprocess":
                        subworkflow_id = op.get("subworkflow_id")
                        input_mapping = op.get("input_mapping")
                        output_variable = op.get("output_variable")
                        
                        if subworkflow_id:
                            new_node["subworkflow_id"] = subworkflow_id
                        if input_mapping is not None:
                            new_node["input_mapping"] = input_mapping
                        if output_variable:
                            new_node["output_variable"] = output_variable
                            
                            # Auto-register output_variable as a workflow input
                            # This allows subsequent decision nodes to reference it
                            existing_input_names = [inp.get("name", "").lower() for inp in new_workflow.get("inputs", [])]
                            if output_variable.lower() not in existing_input_names:
                                new_input = {
                                    "id": f"input_{output_variable.lower().replace(' ', '_')}",
                                    "name": output_variable,
                                    "type": "string",  # Subflow outputs are strings
                                    "description": f"Output from subprocess '{op['label']}'",
                                }
                                if "inputs" not in new_workflow:
                                    new_workflow["inputs"] = []
                                new_workflow["inputs"].append(new_input)
                                # Also update session_state so subsequent ops can reference it
                                if "workflow_analysis" not in session_state:
                                    session_state["workflow_analysis"] = {"inputs": []}
                                session_state["workflow_analysis"]["inputs"].append(new_input)
                        
                        # Validate subprocess node configuration
                        subprocess_errors = validate_subprocess_node(
                            new_node,
                            session_state,
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

                    new_workflow["nodes"].append(new_node)
                    applied_operations.append({"op": "add_node", "node": new_node})

                elif op_type == "modify_node":
                    input_ref = op.get("input_ref")
                    error = input_ref_error(input_ref, session_state)
                    if error:
                        raise ValueError(error)

                    node_id = self._resolve_id(op["node_id"], temp_id_map)
                    node_idx = next(
                        (i for i, n in enumerate(new_workflow["nodes"]) if n["id"] == node_id),
                        None,
                    )
                    if node_idx is None:
                        raise ValueError(f"Node not found: {node_id}")

                    updates = {k: v for k, v in op.items() if k not in ["op", "node_id"]}
                    new_workflow["nodes"][node_idx].update(updates)
                    applied_operations.append(
                        {"op": "modify_node", "node_id": node_id, "updates": updates}
                    )

                elif op_type == "delete_node":
                    node_id = self._resolve_id(op["node_id"], temp_id_map)
                    new_workflow["nodes"] = [
                        n for n in new_workflow["nodes"] if n["id"] != node_id
                    ]
                    new_workflow["edges"] = [
                        e
                        for e in new_workflow["edges"]
                        if e["from"] != node_id and e["to"] != node_id
                    ]
                    applied_operations.append({"op": "delete_node", "node_id": node_id})

                elif op_type == "add_connection":
                    from_id = self._resolve_id(op["from"], temp_id_map)
                    to_id = self._resolve_id(op["to"], temp_id_map)
                    edge_id = f"{from_id}->{to_id}"

                    new_edge = {
                        "id": edge_id,
                        "from": from_id,
                        "to": to_id,
                        "label": op.get("label", ""),
                    }
                    new_workflow["edges"].append(new_edge)
                    applied_operations.append({"op": "add_connection", "edge": new_edge})

                elif op_type == "delete_connection":
                    from_id = self._resolve_id(op["from"], temp_id_map)
                    to_id = self._resolve_id(op["to"], temp_id_map)
                    edge_id = f"{from_id}->{to_id}"

                    new_workflow["edges"] = [
                        e
                        for e in new_workflow["edges"]
                        if not (e["from"] == from_id and e["to"] == to_id)
                    ]
                    applied_operations.append({"op": "delete_connection", "edge_id": edge_id})

                else:
                    raise ValueError(f"Unknown operation type: {op_type}")

        except Exception as exc:
            return {"success": False, "error": f"Failed to apply operations: {str(exc)}"}

        is_valid, errors = self.validator.validate(new_workflow, strict=False)
        if not is_valid:
            return {
                "success": False,
                "error": self.validator.format_errors(errors),
                "error_code": "VALIDATION_FAILED",
            }

        return {
            "success": True,
            "action": "batch_edit",
            "workflow": new_workflow,
            "operations": applied_operations,
            "operation_count": len(applied_operations),
            "message": f"Applied {len(applied_operations)} operations successfully",
        }

    def _resolve_id(self, id_or_temp: str, temp_map: Dict[str, str]) -> str:
        return temp_map.get(id_or_temp, id_or_temp)
