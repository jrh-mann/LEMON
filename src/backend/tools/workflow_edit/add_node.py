"""Add node tool.

This tool adds nodes to the workflow flowchart. For subprocess nodes,
it automatically registers the output as a derived variable with the
correct type inferred from the subworkflow's output definition.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict

from ...validation.workflow_validator import WorkflowValidator
from ..core import Tool, ToolParameter
from ..workflow_input.add import generate_variable_id
from ..workflow_input.helpers import ensure_workflow_analysis, normalize_variable_name
from .helpers import get_node_color, input_ref_error, validate_subprocess_node, get_subworkflow_output_type


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


def validate_decision_condition(condition: Dict[str, Any], variables: list) -> str | None:
    """Validate a decision condition object.
    
    Args:
        condition: The condition dict with input_id, comparator, value, value2
        variables: List of workflow variable definitions
        
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
    
    # Find the variable to check type compatibility
    var_def = None
    for var in variables:
        if var.get("id") == input_id:
            var_def = var
            break
    
    if not var_def:
        return f"condition.input_id '{input_id}' not found in workflow variables"
    
    # Check comparator is valid for this variable type
    var_type = var_def.get("type", "string")
    valid_comparators = COMPARATORS_BY_TYPE.get(var_type, [])
    if comparator not in valid_comparators:
        return (
            f"Comparator '{comparator}' is not valid for variable type '{var_type}'. "
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
    - input_id: The workflow variable to compare (e.g., "var_age_int")
    - comparator: The comparison operator (e.g., "gte", "eq", "str_contains")
    - value: The value to compare against
    - value2: (optional) Second value for range comparisons
    
    For subprocess nodes, the output_variable is automatically registered
    as a derived variable with type inferred from the subworkflow's output.
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
            "Optional: name of workflow variable this node checks (case-insensitive)",
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
            "For subprocess: dict mapping parent variable names to subworkflow input names",
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

        # Ensure workflow_analysis exists with unified variable structure
        workflow_analysis = ensure_workflow_analysis(session_state)

        # Validate input_ref if provided
        input_ref = args.get("input_ref")
        error = input_ref_error(input_ref, session_state)
        if error:
            return {
                "success": False,
                "error": error,
                "error_code": "VARIABLE_NOT_FOUND",
            }

        # Get workflow variables for condition validation
        variables = workflow_analysis.get("variables", [])

        # Validate condition for decision nodes
        node_type = args["type"]
        condition = args.get("condition")
        
        if node_type == "decision":
            if not condition:
                return {
                    "success": False,
                    "error": (
                        "Decision nodes require a 'condition' parameter. "
                        "Provide: {input_id: '<var_id>', comparator: '<comparator>', value: <value>}"
                    ),
                    "error_code": "MISSING_CONDITION",
                }
            
            condition_error = validate_decision_condition(condition, variables)
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
            subworkflow_id = args.get("subworkflow_id")
            input_mapping = args.get("input_mapping")
            output_variable = args.get("output_variable")
            
            if subworkflow_id:
                new_node["subworkflow_id"] = subworkflow_id
            if input_mapping is not None:
                new_node["input_mapping"] = input_mapping
            if output_variable:
                new_node["output_variable"] = output_variable
                
                # Auto-register output_variable as a DERIVED variable (source='subprocess')
                # with type inferred from the subworkflow's output definition
                existing_var_names = [
                    normalize_variable_name(v.get("name", ""))
                    for v in variables
                ]
                
                if normalize_variable_name(output_variable) not in existing_var_names:
                    # Get output type from subworkflow
                    output_info = get_subworkflow_output_type(subworkflow_id or "", session_state)
                    output_type = output_info.get("type", "string") if output_info else "string"
                    output_desc = output_info.get("description") if output_info else None
                    
                    # Generate variable ID with subprocess source
                    var_id = generate_variable_id(output_variable, output_type, "subprocess")
                    
                    # Create derived variable with source='subprocess'
                    new_variable: Dict[str, Any] = {
                        "id": var_id,
                        "name": output_variable,
                        "type": output_type,
                        "source": "subprocess",  # Derived from subprocess execution
                        "source_node_id": node_id,  # Which node produces this
                        "subworkflow_id": subworkflow_id,  # Which subworkflow it comes from
                        "description": output_desc or f"Output from subprocess '{args['label']}'",
                    }
                    
                    # Add to unified variables list
                    workflow_analysis["variables"].append(new_variable)
                    variables = workflow_analysis["variables"]
            
            # Validate subprocess node configuration
            subprocess_errors = validate_subprocess_node(
                new_node,
                session_state,
                check_workflow_exists=True,
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
            "variables": variables,  # Use unified variables instead of inputs
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
            "workflow_analysis": workflow_analysis,  # Return updated analysis for state sync
        }
