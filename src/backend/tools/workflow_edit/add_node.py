"""Add node tool.

This tool adds nodes to the workflow flowchart. For subprocess nodes,
it automatically registers the output as a derived variable with the
correct type inferred from the subworkflow's output definition.

For calculation nodes, validates the operator and operands, and auto-registers
the output variable with source='calculated'.

Multi-workflow architecture:
- Uses current_workflow_id from session_state (implicit binding)
- Loads workflow from database at start
- Auto-saves changes back to database when done
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ...execution.operators import get_operator, get_operator_names, validate_operator_arity
from ..core import WorkflowTool, ToolParameter
from .helpers import (
    build_new_node,
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


def _validate_simple_condition(condition: Dict[str, Any], variables: list) -> str | None:
    """Validate a single simple condition and resolve variable references.

    Accepts either ``variable`` (name-based, preferred) or ``input_id`` (legacy ID).
    When ``variable`` is provided, resolves it to an ``input_id`` via case-insensitive
    name lookup so downstream code (execution engine) works unchanged.

    Args:
        condition: Condition dict with variable (or input_id), comparator, value, value2.
        variables: List of workflow variable definitions.

    Returns:
        Error message if invalid, None if valid.
    """
    # Extract condition fields
    var_name = condition.get("variable")
    input_id = condition.get("input_id")
    comparator = condition.get("comparator")
    value = condition.get("value")

    if var_name:
        # Name-based lookup (case-insensitive)
        normalized = var_name.strip().lower()
        matched = None
        for var in variables:
            if var.get("name", "").strip().lower() == normalized:
                matched = var
                break
        if not matched:
            available = ", ".join(
                v.get("name", "?") for v in variables
            ) or "none"
            return f"Variable '{var_name}' not found. Available: {available}"
        # Inject resolved ID so the execution engine can use it
        condition["input_id"] = matched["id"]
        input_id = matched["id"]
    elif not input_id:
        return "condition.variable is required (name of the workflow variable to check)"

    comparator = condition.get("comparator")
    value = condition.get("value")

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
        available = ", ".join(
            f"{v.get('name', '?')} ({v.get('id')})" for v in variables
        ) or "none"
        return f"Variable '{input_id}' not found. Available: {available}"

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


def validate_decision_condition(condition: Dict[str, Any], variables: list) -> str | None:
    """Validate a decision condition — simple or compound (AND/OR).

    Simple conditions have variable/comparator/value.
    Compound conditions have operator ("and"/"or") and a conditions array
    of 2+ simple conditions.  Nesting is not allowed.

    Args:
        condition: The condition dict (simple or compound).
        variables: List of workflow variable definitions.

    Returns:
        Error message if invalid, None if valid.
    """
    if not isinstance(condition, dict):
        return "condition must be an object with variable, comparator, and value"

    # Compound condition path
    if "operator" in condition:
        operator = condition.get("operator")
        if operator not in ("and", "or"):
            return f"condition.operator must be 'and' or 'or', got '{operator}'"

        sub_conditions = condition.get("conditions")
        if not isinstance(sub_conditions, list):
            return "condition.conditions must be a list"
        if len(sub_conditions) < 2:
            return f"condition.conditions must have at least 2 items, got {len(sub_conditions)}"

        # Validate each sub-condition is simple (no nesting)
        for i, sub in enumerate(sub_conditions):
            if not isinstance(sub, dict):
                return f"condition.conditions[{i}] must be a dict"
            if "operator" in sub:
                return f"condition.conditions[{i}] cannot be compound (no nesting allowed)"
            error = _validate_simple_condition(sub, variables)
            if error:
                return f"condition.conditions[{i}]: {error}"

        return None

    # Simple condition path
    return _validate_simple_condition(condition, variables)


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


class AddNodeTool(WorkflowTool):
    """Add a new node to the workflow.
    
    Supports all node types including subprocess nodes that reference
    other workflows (subflows) and calculation nodes for mathematical operations.
    
    For decision nodes, a 'condition' object is REQUIRED with:
    - variable: The workflow variable name to compare (e.g., "Age")
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
    description = "Add a new node (block) to the workflow."
    parameters = [
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
                "Object with: variable (name string), comparator (string), value (any), value2 (optional for ranges). "
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
            (
                "Optional: data type for end nodes (string, number, bool, json). "
                "Defaults to 'string'. Use 'number' or 'bool' to preserve typed returns."
            ),
            required=False,
        ),
        ToolParameter(
            "output",
            "any",
            (
                "For end nodes: what to return. Smart routing: "
                "variable name (e.g., 'BMI') → returns that variable's typed value; "
                "template with {vars} (e.g., 'Your BMI is {BMI}') → string interpolation; "
                "literal value (e.g., 42, true) → static return value."
            ),
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
            "For subprocess nodes only: name for the variable that stores subworkflow output.",
            required=False,
        ),
    ]

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

        # Delegate all node construction + validation to the shared builder
        new_node, new_variables, build_error = build_new_node(
            params=args,
            variables=variables,
            session_state=session_state,
        )
        if build_error:
            return {
                "success": False,
                "error": build_error,
                "error_code": "NODE_BUILD_FAILED",
            }

        # Append auto-registered variables
        variables_modified = bool(new_variables)
        for var in new_variables:
            variables.append(var)

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
            "new_variables": new_variables,  # Auto-registered calc/subprocess output vars
            "message": f"Added {args['type']} node '{args['label']}' to workflow {workflow_id}",
        }
