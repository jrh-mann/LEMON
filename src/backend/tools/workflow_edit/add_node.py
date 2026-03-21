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
    description = (
        "Add a new node (block) to the active workflow. Returns the created node with a real ID. "
        "Note: Decision nodes should have 2 branches (true/false). You can add them separately "
        "with add_node + add_connection, or use batch_edit_workflow to create the decision + branches "
        "atomically with temporary IDs.\n\n"
        "For SUBPROCESS nodes (subflows): Use subprocess type to call another workflow. "
        "You MUST provide subworkflow_id, input_mapping, and output_variable. "
        "The subworkflow's output will be available as a new input variable that "
        "subsequent decision nodes can reference."
    )
    # Parameters list is kept for reference by other code but the schema is
    # generated from _schema_override due to deeply nested condition/calculation objects.
    parameters = [
        ToolParameter("type", "string", "Node type", required=True,
                      enum=["start", "process", "decision", "subprocess", "calculation", "end"]),
        ToolParameter("label", "string", "Display text for the node", required=True),
        ToolParameter("x", "number", "X coordinate (optional, auto-positions if omitted)", required=False),
        ToolParameter("y", "number", "Y coordinate (optional, auto-positions if omitted)", required=False),
        ToolParameter("output_type", "string", "For 'end' nodes: data type of the output. Use 'number' for all numeric values.",
                      required=False, enum=["string", "number", "bool", "json"]),
        ToolParameter("output", "any",
                      "For 'end' nodes: what to return. variable name, template with {vars}, or literal value.",
                      required=False),
        ToolParameter("output_variable", "string",
                      "For 'subprocess' nodes only: Name for the variable that stores the subworkflow's output.",
                      required=False),
        ToolParameter("condition", "object", "REQUIRED for 'decision' nodes.", required=False),
        ToolParameter("calculation", "object", "REQUIRED for 'calculation' nodes.", required=False),
        ToolParameter("subworkflow_id", "string", "For 'subprocess' nodes: ID of the workflow to call.", required=False),
        ToolParameter("input_mapping", "object", "For 'subprocess' nodes: parent->subworkflow input mapping.", required=False),
    ]

    # Full JSON Schema override — needed because condition and calculation have
    # deeply nested oneOf / object schemas that ToolParameter can't express cleanly.
    _schema_override = {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": ["start", "process", "decision", "subprocess", "calculation", "end"],
                "description": "Node type",
            },
            "label": {
                "type": "string",
                "description": "Display text for the node",
            },
            "x": {
                "type": "number",
                "description": "X coordinate (optional, auto-positions if omitted)",
            },
            "y": {
                "type": "number",
                "description": "Y coordinate (optional, auto-positions if omitted)",
            },
            "output_type": {
                "type": "string",
                "enum": ["string", "number", "bool", "json"],
                "description": "For 'end' nodes: data type of the output. Use 'number' for all numeric values.",
            },
            "output": {
                "description": (
                    "For 'end' nodes: what to return. Smart routing: "
                    "variable name (e.g., 'BMI') returns that variable's typed value; "
                    "template with {vars} (e.g., 'Your BMI is {BMI}') does string interpolation; "
                    "literal value (e.g., 42, true) returns a static value."
                ),
            },
            "output_variable": {
                "type": "string",
                "description": "For 'subprocess' nodes only: Name for the variable that stores the subworkflow's output.",
            },
            "condition": {
                "description": (
                    "REQUIRED for 'decision' nodes. Can be simple or compound.\n"
                    "Simple: {variable, comparator, value, value2?}\n"
                    "Compound: {operator: 'and'|'or', conditions: [simple, simple, ...]}\n"
                    "Use compound when a decision checks MULTIPLE variables (e.g., 'Symptoms AND A1c > 58').\n"
                    "Compound must have >= 2 sub-conditions. No nesting."
                ),
                "oneOf": [
                    {
                        "type": "object",
                        "description": "Simple condition",
                        "properties": {
                            "variable": {"type": "string", "description": "Name of the workflow variable to check (e.g., 'Age', 'Patient Name')"},
                            "comparator": {
                                "type": "string",
                                "enum": [
                                    "eq", "neq", "lt", "lte", "gt", "gte", "within_range",
                                    "is_true", "is_false",
                                    "str_eq", "str_neq", "str_contains", "str_starts_with", "str_ends_with",
                                    "date_eq", "date_before", "date_after", "date_between",
                                    "enum_eq", "enum_neq",
                                ],
                                "description": "Comparison operator",
                            },
                            "value": {"description": "Value to compare against"},
                            "value2": {"description": "Second value for range comparators (within_range, date_between)"},
                        },
                        "required": ["variable", "comparator"],
                    },
                    {
                        "type": "object",
                        "description": "Compound condition (AND/OR)",
                        "properties": {
                            "operator": {"type": "string", "enum": ["and", "or"]},
                            "conditions": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "variable": {"type": "string"},
                                        "comparator": {"type": "string"},
                                        "value": {"description": "Comparison value", "anyOf": [{"type": "string"}, {"type": "number"}, {"type": "boolean"}]},
                                        "value2": {"description": "Second value (for 'between' comparator)", "anyOf": [{"type": "string"}, {"type": "number"}, {"type": "boolean"}]},
                                    },
                                    "required": ["variable", "comparator"],
                                },
                                "minItems": 2,
                            },
                        },
                        "required": ["operator", "conditions"],
                    },
                ],
            },
            "subworkflow_id": {
                "type": "string",
                "description": "For 'subprocess' nodes: ID of the workflow to call as a subflow.",
            },
            "input_mapping": {
                "type": "object",
                "description": "For 'subprocess' nodes: Maps parent input names to subworkflow input names. Example: {\"ParentAge\": \"SubAge\", \"ParentIncome\": \"SubIncome\"}",
                "additionalProperties": {"type": "string"},
            },
            "calculation": {
                "type": "object",
                "description": (
                    "For 'calculation' nodes: Defines a mathematical operation on variables. "
                    "The result is stored in an output variable that can be used by subsequent nodes."
                ),
                "properties": {
                    "output": {
                        "type": "object",
                        "description": "Output variable definition",
                        "properties": {
                            "name": {"type": "string", "description": "Name for the calculated result. Must be alphanumeric with underscores only, no spaces (e.g., 'BMI', 'Total_Score', 'DTI_Ratio')"},
                            "description": {"type": "string", "description": "Description of what this value represents"},
                        },
                        "required": ["name"],
                    },
                    "operator": {
                        "type": "string",
                        "description": "Mathematical operator to apply. See system prompt for full list.",
                        "enum": [
                            "add", "subtract", "multiply", "divide", "floor_divide", "modulo", "power",
                            "negate", "abs", "sqrt", "square", "cube", "reciprocal",
                            "floor", "ceil", "round", "sign",
                            "ln", "log10", "log", "exp",
                            "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
                            "degrees", "radians",
                            "min", "max", "sum", "average", "hypot",
                            "geometric_mean", "harmonic_mean", "variance", "std_dev", "range",
                        ],
                    },
                    "operands": {
                        "type": "array",
                        "description": "List of operands for the operator",
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {
                                    "type": "string",
                                    "enum": ["variable", "literal"],
                                    "description": "'variable' to reference a workflow variable, 'literal' for a constant number",
                                },
                                "ref": {
                                    "type": "string",
                                    "description": "For kind='variable': variable ID (e.g., 'var_weight_number')",
                                },
                                "value": {
                                    "type": "number",
                                    "description": "For kind='literal': the constant numeric value",
                                },
                            },
                            "required": ["kind"],
                        },
                    },
                },
                "required": ["output", "operator", "operands"],
            },
        },
        "required": ["type", "label"],
    }

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
