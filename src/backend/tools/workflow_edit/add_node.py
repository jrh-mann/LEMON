"""Add node tool."""

from __future__ import annotations

import uuid
from typing import Any, Dict

from ...validation.workflow_validator import WorkflowValidator
from ..core import Tool, ToolParameter
from .helpers import get_node_color, input_ref_error, validate_subprocess_node


# Valid comparators by input type - mirrors frontend COMPARATORS_BY_TYPE
COMPARATORS_BY_TYPE = {
    "int": ["eq", "neq", "lt", "lte", "gt", "gte", "within_range"],
    "float": ["eq", "neq", "lt", "lte", "gt", "gte", "within_range"],
    "bool": ["is_true", "is_false"],
    "string": ["str_eq", "str_neq", "str_contains", "str_starts_with", "str_ends_with"],
    "date": ["date_eq", "date_before", "date_after", "date_between"],
    "enum": ["enum_eq", "enum_neq"],
}

ALL_COMPARATORS = [
    "eq", "neq", "lt", "lte", "gt", "gte", "within_range",
    "is_true", "is_false",
    "str_eq", "str_neq", "str_contains", "str_starts_with", "str_ends_with",
    "date_eq", "date_before", "date_after", "date_between",
    "enum_eq", "enum_neq",
]


def validate_decision_condition(condition: Dict[str, Any], inputs: list) -> str | None:
    """Validate a decision condition object.
    
    Args:
        condition: The condition dict with input_id, comparator, value, value2
        inputs: List of workflow input definitions
        
    Returns:
        Error message if invalid, None if valid.
    """
    if not isinstance(condition, dict):
        return "condition must be an object with input_id, comparator, and value"
    
    input_id = condition.get("input_id")
    comparator = condition.get("comparator")
    value = condition.get("value")
    
    if not input_id:
        return "condition.input_id is required"
    if not comparator:
        return "condition.comparator is required"
    if value is None and comparator not in ("is_true", "is_false"):
        return f"condition.value is required for comparator '{comparator}'"
    
    # Validate comparator is known
    if comparator not in ALL_COMPARATORS:
        return f"Unknown comparator '{comparator}'. Valid: {ALL_COMPARATORS}"
    
    # Find the input to check type compatibility
    input_def = None
    for inp in inputs:
        if inp.get("id") == input_id:
            input_def = inp
            break
    
    if not input_def:
        return f"condition.input_id '{input_id}' not found in workflow inputs"
    
    # Check comparator is valid for this input type
    input_type = input_def.get("type", "string")
    valid_comparators = COMPARATORS_BY_TYPE.get(input_type, [])
    if comparator not in valid_comparators:
        return (
            f"Comparator '{comparator}' is not valid for input type '{input_type}'. "
            f"Valid comparators: {valid_comparators}"
        )
    
    # Check value2 is provided for range comparators
    if comparator in ("within_range", "date_between"):
        if condition.get("value2") is None:
            return f"condition.value2 is required for comparator '{comparator}'"
    
    return None


class AddNodeTool(Tool):
    """Add a new node to the workflow.
    
    Supports all node types including subprocess nodes that reference
    other workflows (subflows).
    
    For decision nodes, a 'condition' object is REQUIRED with:
    - input_id: The workflow input to compare (e.g., "input_age_int")
    - comparator: The comparison operator (e.g., "gte", "eq", "str_contains")
    - value: The value to compare against
    - value2: (optional) Second value for range comparisons
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
        # Decision node condition (REQUIRED for decision nodes)
        ToolParameter(
            "condition",
            "object",
            (
                "REQUIRED for decision nodes: Structured condition to evaluate. "
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

        # Validate input_ref if provided
        input_ref = args.get("input_ref")
        error = input_ref_error(input_ref, session_state)
        if error:
            return {
                "success": False,
                "error": error,
                "error_code": "INPUT_NOT_FOUND",
            }

        # Get workflow inputs for condition validation
        inputs = session_state.get("workflow_analysis", {}).get("inputs", [])

        # Validate condition for decision nodes
        node_type = args["type"]
        condition = args.get("condition")
        
        if node_type == "decision":
            if not condition:
                return {
                    "success": False,
                    "error": (
                        "Decision nodes require a 'condition' parameter. "
                        "Provide: {input_id: '<input_id>', comparator: '<comparator>', value: <value>}"
                    ),
                    "error_code": "MISSING_CONDITION",
                }
            
            condition_error = validate_decision_condition(condition, inputs)
            if condition_error:
                return {
                    "success": False,
                    "error": condition_error,
                    "error_code": "INVALID_CONDITION",
                }

        node_id = f"node_{uuid.uuid4().hex[:8]}"
        new_node = {
            "id": node_id,
            "type": node_type,
            "label": args["label"],
            "x": args.get("x", 0),
            "y": args.get("y", 0),
            "color": get_node_color(node_type),
        }

        if input_ref:
            new_node["input_ref"] = input_ref
        
        # Add condition for decision nodes
        if condition:
            new_node["condition"] = condition
        
        # Add output configuration for 'end' nodes
        if node_type == "end":
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
        if node_type == "subprocess":
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
            "message": f"Added {node_type} node '{args['label']}'",
        }
