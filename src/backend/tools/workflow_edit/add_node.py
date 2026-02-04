"""Add node tool.

This tool adds nodes to the workflow flowchart. For subprocess nodes,
it automatically registers the output as a derived variable with the
correct type inferred from the subworkflow's output definition.

For calculation nodes, validates the operator and operands, and auto-registers
the output variable with source='calculated'.

Multi-workflow architecture:
- Requires workflow_id parameter (workflow must exist in library)
- Loads workflow from database at start
- Auto-saves changes back to database when done
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from ...execution.operators import get_operator, get_operator_names, validate_operator_arity
from ...validation.workflow_validator import WorkflowValidator
from ..core import Tool, ToolParameter
from ..workflow_input.add import generate_variable_id
from ..workflow_input.helpers import normalize_variable_name
from .helpers import (
    get_node_color,
    validate_subprocess_node,
    get_subworkflow_output_type,
    load_workflow_for_tool,
    save_workflow_changes,
)


# Valid comparators by input type - mirrors frontend COMPARATORS_BY_TYPE
# 'number' is the unified numeric type that supports all numeric comparators
COMPARATORS_BY_TYPE = {
    "number": ["eq", "neq", "lt", "lte", "gt", "gte", "within_range"],
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


def validate_calculation(
    calculation: Dict[str, Any],
    variables: List[Dict[str, Any]],
) -> Optional[str]:
    """Validate a calculation object for a calculation node.
    
    Calculation schema:
    {
        "output": {"name": str, "description": str (optional)},
        "operator": str (must be a valid operator name),
        "operands": [
            {"kind": "variable", "ref": str (variable ID)},
            {"kind": "literal", "value": number}
        ]
    }
    
    Args:
        calculation: The calculation dict to validate
        variables: List of workflow variable definitions
        
    Returns:
        Error message if invalid, None if valid.
    """
    if not isinstance(calculation, dict):
        return "calculation must be an object with output, operator, and operands"
    
    # Validate output
    output = calculation.get("output")
    if not output:
        return "calculation.output is required"
    if not isinstance(output, dict):
        return "calculation.output must be an object with 'name'"
    output_name = output.get("name")
    if not output_name:
        return "calculation.output.name is required"
    if not isinstance(output_name, str):
        return "calculation.output.name must be a string"
    # Validate output name is a valid identifier
    if not output_name.replace("_", "").isalnum():
        return f"calculation.output.name must be alphanumeric with underscores, got '{output_name}'"
    
    # Validate operator
    operator = calculation.get("operator")
    if not operator:
        return "calculation.operator is required"
    if not isinstance(operator, str):
        return "calculation.operator must be a string"
    
    op = get_operator(operator)
    if op is None:
        return f"Unknown operator '{operator}'. Valid operators: {', '.join(get_operator_names())}"
    
    # Validate operands
    operands = calculation.get("operands")
    if not operands:
        return "calculation.operands is required"
    if not isinstance(operands, list):
        return "calculation.operands must be an array"
    if len(operands) == 0:
        return "calculation.operands must not be empty"
    
    # Validate arity
    arity_error = validate_operator_arity(operator, len(operands))
    if arity_error:
        return arity_error
    
    # Build map of variable IDs for reference validation
    var_ids = {v.get("id") for v in variables if v.get("id")}
    var_names = {v.get("name") for v in variables if v.get("name")}
    
    # Validate each operand
    for i, operand in enumerate(operands):
        if not isinstance(operand, dict):
            return f"calculation.operands[{i}] must be an object with 'kind'"
        
        kind = operand.get("kind")
        if kind not in ("variable", "literal"):
            return f"calculation.operands[{i}].kind must be 'variable' or 'literal', got '{kind}'"
        
        if kind == "variable":
            ref = operand.get("ref")
            if not ref:
                return f"calculation.operands[{i}].ref is required for variable operands"
            # Allow referencing by ID or name
            if ref not in var_ids and ref not in var_names:
                return (
                    f"calculation.operands[{i}].ref '{ref}' not found in workflow variables. "
                    f"Available variable IDs: {sorted(var_ids)}"
                )
        elif kind == "literal":
            value = operand.get("value")
            if value is None:
                return f"calculation.operands[{i}].value is required for literal operands"
            if not isinstance(value, (int, float)):
                return f"calculation.operands[{i}].value must be a number, got {type(value).__name__}"
    
    return None


class AddNodeTool(Tool):
    """Add a new node to the workflow.
    
    Supports all node types including subprocess nodes that reference
    other workflows (subflows) and calculation nodes for mathematical operations.
    
    For decision nodes, a 'condition' object is REQUIRED with:
    - input_id: The workflow variable to compare (e.g., "var_age_int")
    - comparator: The comparison operator (e.g., "gte", "eq", "str_contains")
    - value: The value to compare against
    - value2: (optional) Second value for range comparisons
    
    For calculation nodes, a 'calculation' object is REQUIRED with:
    - output: {"name": "ResultVar", "description": "Optional description"}
    - operator: The operator name (e.g., "add", "divide", "sqrt")
    - operands: Array of {"kind": "variable", "ref": "var_id"} or {"kind": "literal", "value": 123}
    
    For subprocess nodes, the output_variable is automatically registered
    as a derived variable with type inferred from the subworkflow's output.
    """

    name = "add_node"
    description = "Add a new node (block) to the workflow. Requires workflow_id."
    parameters = [
        # workflow_id is REQUIRED and must be first
        ToolParameter(
            "workflow_id",
            "string",
            "ID of the workflow to add the node to (from create_workflow)",
            required=True,
        ),
        ToolParameter(
            "type",
            "string",
            "Node type: start, process, decision, subprocess, calculation, or end",
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
        # Calculation node config (REQUIRED for calculation nodes)
        ToolParameter(
            "calculation",
            "object",
            (
                "REQUIRED for calculation nodes: Mathematical operation to perform. "
                "Object with: output {name, description?}, operator (string), operands (array). "
                "Each operand is {kind: 'variable', ref: 'var_id'} or {kind: 'literal', value: number}. "
                "Operators: add, subtract, multiply, divide, power, sqrt, abs, min, max, average, etc."
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
        workflow_id = args.get("workflow_id")
        
        # Load workflow from database
        workflow_data, error = load_workflow_for_tool(workflow_id, session_state)
        if error:
            return error
        
        # Extract workflow components
        nodes = workflow_data["nodes"]
        edges = workflow_data["edges"]
        variables = workflow_data["variables"]

        # Validate condition for decision nodes
        node_type = args["type"]
        condition = args.get("condition")
        calculation = args.get("calculation")
        
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
        
        # Validate calculation for calculation nodes
        if node_type == "calculation":
            if not calculation:
                return {
                    "success": False,
                    "error": (
                        "Calculation nodes require a 'calculation' parameter. "
                        "Provide: {output: {name: 'VarName'}, operator: 'add', operands: [{kind: 'variable', ref: 'var_id'}, ...]}"
                    ),
                    "error_code": "MISSING_CALCULATION",
                }
            
            calculation_error = validate_calculation(calculation, variables)
            if calculation_error:
                return {
                    "success": False,
                    "error": calculation_error,
                    "error_code": "INVALID_CALCULATION",
                }

        # Create new node
        node_id = f"node_{uuid.uuid4().hex[:8]}"
        new_node = {
            "id": node_id,
            "type": node_type,
            "label": args["label"],
            "x": args.get("x", 0),
            "y": args.get("y", 0),
            "color": get_node_color(node_type),
        }
        
        # Track if variables list is modified (for auto-save)
        variables_modified = False

        # Add condition for decision nodes
        if condition:
            new_node["condition"] = condition
        
        # Add calculation for calculation nodes and auto-register output variable
        if node_type == "calculation" and calculation:
            new_node["calculation"] = calculation
            
            # Auto-register the output variable as a calculated variable
            output_def = calculation["output"]
            output_name = output_def["name"]
            output_desc = output_def.get("description")
            
            existing_var_names = [
                normalize_variable_name(v.get("name", ""))
                for v in variables
            ]
            
            if normalize_variable_name(output_name) not in existing_var_names:
                # Calculate output is always 'number' type
                var_id = generate_variable_id(output_name, "number", "calculated")
                
                new_variable: Dict[str, Any] = {
                    "id": var_id,
                    "name": output_name,
                    "type": "number",  # Calculation output is always number
                    "source": "calculated",  # Derived from calculation
                    "source_node_id": node_id,  # Which node produces this
                    "description": output_desc or f"Calculated by '{args['label']}'",
                }
                
                variables.append(new_variable)
                variables_modified = True
        
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
            subworkflow_id_param = args.get("subworkflow_id")
            input_mapping = args.get("input_mapping")
            output_variable = args.get("output_variable")
            
            if subworkflow_id_param:
                new_node["subworkflow_id"] = subworkflow_id_param
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
                    output_info = get_subworkflow_output_type(subworkflow_id_param or "", session_state)
                    output_type_val = output_info.get("type", "string") if output_info else "string"
                    output_desc = output_info.get("description") if output_info else None
                    
                    # Generate variable ID with subprocess source
                    var_id = generate_variable_id(output_variable, output_type_val, "subprocess")
                    
                    # Create derived variable with source='subprocess'
                    new_variable: Dict[str, Any] = {
                        "id": var_id,
                        "name": output_variable,
                        "type": output_type_val,
                        "source": "subprocess",  # Derived from subprocess execution
                        "source_node_id": node_id,  # Which node produces this
                        "subworkflow_id": subworkflow_id_param,  # Which subworkflow it comes from
                        "description": output_desc or f"Output from subprocess '{args['label']}'",
                    }
                    
                    # Add to variables list
                    variables.append(new_variable)
                    variables_modified = True
            
            # Validate subprocess node configuration
            # Build a mock session_state for validation that includes the updated variables
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

        # Add node to list
        nodes.append(new_node)

        # Validate the workflow
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
        save_kwargs = {"nodes": nodes}
        if variables_modified:
            save_kwargs["variables"] = variables
        
        save_error = save_workflow_changes(workflow_id, session_state, **save_kwargs)
        if save_error:
            return save_error

        return {
            "success": True,
            "workflow_id": workflow_id,
            "action": "add_node",
            "node": new_node,
            "message": f"Added {node_type} node '{args['label']}' to workflow {workflow_id}",
        }
