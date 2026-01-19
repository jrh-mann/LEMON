"""Workflow manipulation tools for the orchestrator."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from ..validation.workflow_validator import WorkflowValidator
from .core import Tool, ToolParameter


class GetCurrentWorkflowTool(Tool):
    """Get the current workflow displayed on the canvas."""

    name = "get_current_workflow"
    description = "Get the current workflow displayed on the canvas as JSON (nodes and edges)."
    parameters: List[ToolParameter] = []

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        workflow = session_state.get("current_workflow", {"nodes": [], "edges": []})

        # Build semantic descriptions to help the LLM
        node_descriptions = []
        for node in workflow.get("nodes", []):
            desc = f"- {node['id']}: \"{node['label']}\" (type: {node['type']})"
            node_descriptions.append(desc)

        edge_descriptions = []
        for edge in workflow.get("edges", []):
            from_label = next(
                (n["label"] for n in workflow.get("nodes", []) if n["id"] == edge["from"]),
                "?",
            )
            to_label = next(
                (n["label"] for n in workflow.get("nodes", []) if n["id"] == edge["to"]),
                "?",
            )
            label_part = f" [{edge.get('label', '')}]" if edge.get("label") else ""
            desc = f"- {edge['from']} → {edge['to']}: \"{from_label}\"{label_part} → \"{to_label}\""
            edge_descriptions.append(desc)

        return {
            "success": True,
            "workflow": workflow,
            "node_count": len(workflow.get("nodes", [])),
            "edge_count": len(workflow.get("edges", [])),
            "summary": {
                "node_count": len(workflow.get("nodes", [])),
                "edge_count": len(workflow.get("edges", [])),
                "node_descriptions": (
                    "\n".join(node_descriptions) if node_descriptions else "No nodes"
                ),
                "edge_descriptions": (
                    "\n".join(edge_descriptions) if edge_descriptions else "No connections"
                ),
            },
        }


class AddNodeTool(Tool):
    """Add a new node to the workflow."""

    name = "add_node"
    description = "Add a new node (block) to the workflow."
    parameters = [
        ToolParameter(
            "type",
            "string",
            "Node type: start, process, decision, subprocess, or end",
            required=True,
        ),
        ToolParameter("label", "string", "Display text for the node", required=True),
        ToolParameter(
            "x",
            "number",
            "X coordinate (optional, auto-positions if omitted)",
            required=False,
        ),
        ToolParameter(
            "y",
            "number",
            "Y coordinate (optional, auto-positions if omitted)",
            required=False,
        ),
    ]

    def __init__(self):
        self.validator = WorkflowValidator()

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        # Get current workflow from session state
        session_state = kwargs.get("session_state", {})
        current_workflow = session_state.get("current_workflow", {"nodes": [], "edges": []})

        # Create the new node
        node_id = f"node_{uuid.uuid4().hex[:8]}"
        new_node = {
            "id": node_id,
            "type": args["type"],
            "label": args["label"],
            "x": args.get("x", 0),
            "y": args.get("y", 0),
            "color": self._get_node_color(args["type"]),
        }

        # Apply change to a copy
        new_workflow = {
            "nodes": [*current_workflow.get("nodes", []), new_node],
            "edges": current_workflow.get("edges", []),
        }

        # Validate
        is_valid, errors = self.validator.validate(new_workflow)
        if not is_valid:
            return {
                "success": False,
                "error": self.validator.format_errors(errors),
                "error_code": "VALIDATION_FAILED",
            }

        # Return the change (frontend will apply it)
        return {
            "success": True,
            "action": "add_node",
            "node": new_node,
            "message": f"Added {args['type']} node '{args['label']}'",
        }

    def _get_node_color(self, node_type: str) -> str:
        colors = {
            "start": "teal",
            "decision": "amber",
            "end": "green",
            "subprocess": "rose",
            "process": "slate",
        }
        return colors.get(node_type, "slate")


class ModifyNodeTool(Tool):
    """Modify an existing node's properties."""

    name = "modify_node"
    description = "Update an existing node's label, type, or position."
    parameters = [
        ToolParameter("node_id", "string", "ID of the node to modify", required=True),
        ToolParameter("label", "string", "New label text", required=False),
        ToolParameter("type", "string", "New node type", required=False),
        ToolParameter("x", "number", "New X coordinate", required=False),
        ToolParameter("y", "number", "New Y coordinate", required=False),
    ]

    def __init__(self):
        self.validator = WorkflowValidator()

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        current_workflow = session_state.get("current_workflow", {"nodes": [], "edges": []})

        node_id = args.get("node_id")
        updates = {k: v for k, v in args.items() if k != "node_id" and v is not None}

        # Find the node
        node_idx = next(
            (i for i, n in enumerate(current_workflow.get("nodes", [])) if n["id"] == node_id),
            None,
        )

        if node_idx is None:
            return {
                "success": False,
                "error": f"Node not found: {node_id}",
                "error_code": "NODE_NOT_FOUND",
            }

        # Apply changes to a copy
        new_workflow = {
            "nodes": [dict(n) for n in current_workflow.get("nodes", [])],
            "edges": current_workflow.get("edges", []),
        }
        new_workflow["nodes"][node_idx].update(updates)

        # Validate
        is_valid, errors = self.validator.validate(new_workflow)
        if not is_valid:
            return {
                "success": False,
                "error": self.validator.format_errors(errors),
                "error_code": "VALIDATION_FAILED",
            }

        return {
            "success": True,
            "action": "modify_node",
            "node_id": node_id,
            "updates": updates,
            "message": f"Updated node {node_id}",
        }


class DeleteNodeTool(Tool):
    """Delete a node from the workflow."""

    name = "delete_node"
    description = "Remove a node and all connected edges from the workflow."
    parameters = [
        ToolParameter("node_id", "string", "ID of the node to delete", required=True),
    ]

    def __init__(self):
        self.validator = WorkflowValidator()

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        current_workflow = session_state.get("current_workflow", {"nodes": [], "edges": []})

        node_id = args.get("node_id")

        # Apply deletion to a copy
        new_workflow = {
            "nodes": [n for n in current_workflow.get("nodes", []) if n["id"] != node_id],
            "edges": [
                e
                for e in current_workflow.get("edges", [])
                if e["from"] != node_id and e["to"] != node_id
            ],
        }

        # Validate
        is_valid, errors = self.validator.validate(new_workflow)
        if not is_valid:
            return {
                "success": False,
                "error": self.validator.format_errors(errors),
                "error_code": "VALIDATION_FAILED",
            }

        return {
            "success": True,
            "action": "delete_node",
            "node_id": node_id,
            "message": f"Deleted node {node_id} and connected edges",
        }


class AddConnectionTool(Tool):
    """Connect two nodes with an edge."""

    name = "add_connection"
    description = "Create an edge connecting two nodes."
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

    def __init__(self):
        self.validator = WorkflowValidator()

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        current_workflow = session_state.get("current_workflow", {"nodes": [], "edges": []})

        from_id = args.get("from_node_id")
        to_id = args.get("to_node_id")
        label = args.get("label", "")
        edge_id = f"{from_id}->{to_id}"

        new_edge = {
            "id": edge_id,
            "from": from_id,
            "to": to_id,
            "label": label,
        }

        # Apply change to a copy
        new_workflow = {
            "nodes": current_workflow.get("nodes", []),
            "edges": [*current_workflow.get("edges", []), new_edge],
        }

        # Validate
        is_valid, errors = self.validator.validate(new_workflow)
        if not is_valid:
            return {
                "success": False,
                "error": self.validator.format_errors(errors),
                "error_code": "VALIDATION_FAILED",
            }

        return {
            "success": True,
            "action": "add_connection",
            "edge": new_edge,
            "message": f"Connected {from_id} to {to_id}",
        }


class DeleteConnectionTool(Tool):
    """Remove an edge from the workflow."""

    name = "delete_connection"
    description = "Remove a connection between two nodes."
    parameters = [
        ToolParameter("from_node_id", "string", "Source node ID", required=True),
        ToolParameter("to_node_id", "string", "Target node ID", required=True),
    ]

    def __init__(self):
        self.validator = WorkflowValidator()

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        current_workflow = session_state.get("current_workflow", {"nodes": [], "edges": []})

        from_id = args.get("from_node_id")
        to_id = args.get("to_node_id")
        edge_id = f"{from_id}->{to_id}"

        # Apply deletion to a copy
        new_workflow = {
            "nodes": current_workflow.get("nodes", []),
            "edges": [
                e
                for e in current_workflow.get("edges", [])
                if not (e["from"] == from_id and e["to"] == to_id)
            ],
        }

        # Validate
        is_valid, errors = self.validator.validate(new_workflow)
        if not is_valid:
            return {
                "success": False,
                "error": self.validator.format_errors(errors),
                "error_code": "VALIDATION_FAILED",
            }

        return {
            "success": True,
            "action": "delete_connection",
            "edge_id": edge_id,
            "message": f"Removed connection from {from_id} to {to_id}",
        }


class BatchEditWorkflowTool(Tool):
    """Apply multiple workflow changes atomically."""

    name = "batch_edit_workflow"
    description = """
    Apply multiple workflow changes in a single atomic operation.
    All changes are validated together - if any fail validation, none are applied.
    Use this when you need to make multiple related changes (e.g., add a node AND connect it).
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

        # Clone workflow
        new_workflow = {
            "nodes": [dict(n) for n in current_workflow.get("nodes", [])],
            "edges": [dict(e) for e in current_workflow.get("edges", [])],
        }

        # Map temp IDs to real IDs
        temp_id_map: Dict[str, str] = {}
        applied_operations: List[Dict[str, Any]] = []

        try:
            for op in operations:
                op_type = op.get("op")

                if op_type == "add_node":
                    # Generate real ID
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
                        "color": self._get_node_color(op["type"]),
                    }
                    new_workflow["nodes"].append(new_node)
                    applied_operations.append({"op": "add_node", "node": new_node})

                elif op_type == "modify_node":
                    node_id = self._resolve_id(op["node_id"], temp_id_map)
                    node_idx = next(
                        (i for i, n in enumerate(new_workflow["nodes"]) if n["id"] == node_id),
                        None,
                    )
                    if node_idx is None:
                        raise ValueError(f"Node not found: {node_id}")

                    # Apply updates
                    updates = {k: v for k, v in op.items() if k not in ["op", "node_id"]}
                    new_workflow["nodes"][node_idx].update(updates)
                    applied_operations.append(
                        {"op": "modify_node", "node_id": node_id, "updates": updates}
                    )

                elif op_type == "delete_node":
                    node_id = self._resolve_id(op["node_id"], temp_id_map)
                    # Remove node
                    new_workflow["nodes"] = [
                        n for n in new_workflow["nodes"] if n["id"] != node_id
                    ]
                    # Remove connected edges
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

        except Exception as e:
            return {"success": False, "error": f"Failed to apply operations: {str(e)}"}

        # Validate the entire result
        is_valid, errors = self.validator.validate(new_workflow)
        if not is_valid:
            return {
                "success": False,
                "error": self.validator.format_errors(errors),
                "error_code": "VALIDATION_FAILED",
            }

        # Success - return all changes
        return {
            "success": True,
            "action": "batch_edit",
            "operations": applied_operations,
            "operation_count": len(applied_operations),
            "message": f"Applied {len(applied_operations)} operations successfully",
        }

    def _resolve_id(self, id_or_temp: str, temp_map: Dict[str, str]) -> str:
        """Resolve a temporary ID to a real ID, or return as-is."""
        return temp_map.get(id_or_temp, id_or_temp)

    def _get_node_color(self, node_type: str) -> str:
        """Get color based on node type."""
        colors = {
            "start": "teal",
            "decision": "amber",
            "end": "green",
            "subprocess": "rose",
            "process": "slate",
        }
        return colors.get(node_type, "slate")
