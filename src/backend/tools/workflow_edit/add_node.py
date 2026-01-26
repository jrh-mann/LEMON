"""Add node tool."""

from __future__ import annotations

import uuid
from typing import Any, Dict

from ...validation.workflow_validator import WorkflowValidator
from ..core import Tool, ToolParameter
from .helpers import get_node_color, input_ref_error, validate_subprocess_node


class AddNodeTool(Tool):
    """Add a new node to the workflow.
    
    Supports all node types including subprocess nodes that reference
    other workflows (subflows).
    """

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

        # Validate input_ref if provided
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

        # Add subprocess-specific fields
        if args["type"] == "subprocess":
            # These are required for subprocess nodes
            subworkflow_id = args.get("subworkflow_id")
            input_mapping = args.get("input_mapping")
            output_variable = args.get("output_variable")
            
            if subworkflow_id:
                new_node["subworkflow_id"] = subworkflow_id
            if input_mapping is not None:
                new_node["input_mapping"] = input_mapping
            if output_variable:
                new_node["output_variable"] = output_variable
                
                # Auto-register output_variable as a workflow input
                # This allows subsequent decision nodes to reference it
                workflow_analysis = session_state.get("workflow_analysis", {})
                existing_inputs = workflow_analysis.get("inputs", [])
                existing_input_names = [inp.get("name", "").lower() for inp in existing_inputs]
                
                if output_variable.lower() not in existing_input_names:
                    new_input = {
                        "id": f"input_{output_variable.lower().replace(' ', '_')}",
                        "name": output_variable,
                        "type": "string",  # Subflow outputs are strings
                        "description": f"Output from subprocess '{args['label']}'",
                    }
                    # Update session_state so validation and subsequent tools see it
                    if "workflow_analysis" not in session_state:
                        session_state["workflow_analysis"] = {"inputs": []}
                    if "inputs" not in session_state["workflow_analysis"]:
                        session_state["workflow_analysis"]["inputs"] = []
                    session_state["workflow_analysis"]["inputs"].append(new_input)
                    inputs = session_state["workflow_analysis"]["inputs"]
            
            # Validate subprocess node configuration
            subprocess_errors = validate_subprocess_node(
                new_node,
                session_state,
                check_workflow_exists=True,  # Validate at creation time
            )
            if subprocess_errors:
                return {
                    "success": False,
                    "error": "\n".join(subprocess_errors),
                    "error_code": "SUBPROCESS_VALIDATION_FAILED",
                }
        else:
            # Still allow subprocess fields on other types (for type changes)
            if "subworkflow_id" in args:
                new_node["subworkflow_id"] = args["subworkflow_id"]
            if "input_mapping" in args:
                new_node["input_mapping"] = args["input_mapping"]
            if "output_variable" in args:
                new_node["output_variable"] = args["output_variable"]

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
