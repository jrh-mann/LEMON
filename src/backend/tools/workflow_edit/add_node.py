"""Add node tool."""

from __future__ import annotations

import uuid
from typing import Any, Dict

from ...validation.workflow_validator import WorkflowValidator
from ..core import Tool, ToolParameter
from .helpers import get_node_color, input_ref_error


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
        ToolParameter(
            "input_ref",
            "string",
            "Optional: name of workflow input this node checks (case-insensitive)",
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
    ]

    def __init__(self):
        self.validator = WorkflowValidator()

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        current_workflow = session_state.get("current_workflow", {"nodes": [], "edges": []})

        input_ref = args.get("input_ref")
        error = input_ref_error(input_ref, session_state)
        if error:
            return {
                "success": False,
                "error": error,
                "error_code": "INPUT_NOT_FOUND",
            }

        node_id = f"node_{uuid.uuid4().hex[:8]}"
        new_node = {
            "id": node_id,
            "type": args["type"],
            "label": args["label"],
            "x": args.get("x", 0),
            "y": args.get("y", 0),
            "color": get_node_color(args["type"]),
        }

        if input_ref:
            new_node["input_ref"] = input_ref
        
        # Add output configuration for 'end' nodes
        if args["type"] == "end":
            new_node["output_type"] = args.get("output_type", "string")
            new_node["output_template"] = args.get("output_template", "")
            new_node["output_value"] = args.get("output_value", None)
        else:
            # Still allow manual setting for other types if passed (future proofing)
            if "output_type" in args:
                new_node["output_type"] = args["output_type"]
            if "output_template" in args:
                new_node["output_template"] = args["output_template"]
            if "output_value" in args:
                new_node["output_value"] = args["output_value"]

        inputs = session_state.get("workflow_analysis", {}).get("inputs", [])
        new_workflow = {
            "nodes": [*current_workflow.get("nodes", []), new_node],
            "edges": current_workflow.get("edges", []),
            "inputs": inputs,
        }

        is_valid, errors = self.validator.validate(new_workflow, strict=False)
        if not is_valid:
            return {
                "success": False,
                "error": self.validator.format_errors(errors),
                "error_code": "VALIDATION_FAILED",
            }

        return {
            "success": True,
            "action": "add_node",
            "node": new_node,
            "message": f"Added {args['type']} node '{args['label']}'",
        }
