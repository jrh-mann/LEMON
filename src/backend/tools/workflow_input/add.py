"""Add workflow variable tool.

This tool registers user-input variables for the workflow. These are variables
that users provide values for at execution time. For subprocess outputs or
calculated variables, those are created automatically when adding nodes.
"""

from __future__ import annotations

import re
from typing import Any, Dict

from ..core import Tool, ToolParameter
from .helpers import ensure_workflow_analysis, normalize_variable_name


# Map user-friendly types to internal types used by condition validation
# and the execution interpreter. For 'number', we use 'float' as default
# since it's more general (accepts both integers and decimals).
USER_TYPE_TO_INTERNAL = {
    "string": "string",
    "number": "float",  # Use float for number type (more general)
    "boolean": "bool",
    "enum": "enum",
}


def generate_variable_id(name: str, internal_type: str, source: str = "input") -> str:
    """Generate deterministic variable ID from name, type, and source.
    
    Format: var_{slug}_{type} for inputs, or var_{source}_{slug}_{type} for derived
    
    Args:
        name: Variable name (e.g., "Patient Age")
        internal_type: Internal type (e.g., "int", "float", "bool", "string")
        source: Variable source ("input", "subprocess", "calculated", "constant")
        
    Returns:
        Variable ID (e.g., "var_patient_age_float", "var_sub_creditscore_int")
    """
    # Slugify: lowercase, replace non-alphanumeric with underscore, strip trailing
    slug = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
    
    if source == "input":
        return f"var_{slug}_{internal_type}"
    else:
        # For derived variables, include abbreviated source prefix
        source_prefix = {
            "subprocess": "sub",
            "calculated": "calc",
            "constant": "const",
        }.get(source, source[:4])
        return f"var_{source_prefix}_{slug}_{internal_type}"


# Backwards compatibility alias
def generate_input_id(name: str, internal_type: str) -> str:
    """Generate input variable ID (backwards compatibility wrapper)."""
    return generate_variable_id(name, internal_type, "input")


class AddWorkflowVariableTool(Tool):
    """Register a user-input variable for the workflow.
    
    This tool creates variables with source='input', meaning users provide
    values at execution time. These variables appear in the Variables tab
    under the 'Inputs' section.
    """

    name = "add_workflow_variable"
    aliases = ["add_workflow_input"]  # Backwards compatibility
    description = (
        "Register an input variable for the workflow. This variable will appear in the Variables tab "
        "where users can provide values at execution time. Use this when the workflow needs data from "
        "users (e.g., 'Patient Age', 'Email Address', 'Order Amount'). For subprocess outputs, use "
        "the output_variable parameter when adding a subprocess node instead."
    )
    parameters = [
        ToolParameter(
            "name",
            "string",
            "Human-readable variable name (e.g., 'Patient Age', 'Email Address')",
            required=True,
        ),
        ToolParameter(
            "type",
            "string",
            "Variable type: 'string', 'number', 'boolean', or 'enum'",
            required=True,
        ),
        ToolParameter(
            "description",
            "string",
            "Optional description of what this variable represents",
            required=False,
        ),
        ToolParameter(
            "enum_values",
            "array",
            "For enum type: array of allowed values (e.g., ['Male', 'Female', 'Other'])",
            required=False,
        ),
        ToolParameter(
            "range_min",
            "number",
            "For number type: minimum allowed value",
            required=False,
        ),
        ToolParameter(
            "range_max",
            "number",
            "For number type: maximum allowed value",
            required=False,
        ),
    ]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        workflow_analysis = ensure_workflow_analysis(session_state)

        name = args.get("name")
        var_type = args.get("type")

        if not name or not isinstance(name, str) or not name.strip():
            return {"success": False, "error": "Variable 'name' is required and must be a non-empty string"}

        if not var_type or var_type not in ["string", "number", "boolean", "enum"]:
            return {
                "success": False,
                "error": "Variable 'type' must be one of: string, number, boolean, enum"
            }

        if var_type == "enum":
            enum_values = args.get("enum_values")
            if not enum_values or not isinstance(enum_values, list) or len(enum_values) == 0:
                return {
                    "success": False,
                    "error": "enum_values is required for type 'enum' and must be a non-empty array"
                }

        # Check for duplicate names (case-insensitive) across ALL variables
        normalized_name = normalize_variable_name(name)
        for existing in workflow_analysis.get("variables", []):
            if normalize_variable_name(existing.get("name", "")) == normalized_name:
                return {
                    "success": False,
                    "error": f"Variable '{name}' already exists (case-insensitive check)"
                }

        # Map user-friendly type to internal type
        internal_type = USER_TYPE_TO_INTERNAL.get(var_type, "string")
        
        # For number type with range constraints, determine if int or float
        # based on whether min/max values are integers
        if var_type == "number":
            range_min = args.get("range_min")
            range_max = args.get("range_max")
            # If both range values are provided and both are integers, use int
            if range_min is not None and range_max is not None:
                if isinstance(range_min, int) and isinstance(range_max, int):
                    # Check they're not float-like (e.g., 5.0)
                    if range_min == int(range_min) and range_max == int(range_max):
                        internal_type = "int"
        
        # Generate deterministic ID for input variable
        var_id = generate_variable_id(name.strip(), internal_type, "input")

        # Create variable object with source='input'
        variable_obj: Dict[str, Any] = {
            "id": var_id,
            "name": name.strip(),
            "type": internal_type,
            "source": "input",  # This is a user-provided input
        }

        if args.get("description"):
            variable_obj["description"] = args["description"]

        if var_type == "enum" and args.get("enum_values"):
            variable_obj["enum_values"] = args["enum_values"]

        if var_type == "number":
            range_min = args.get("range_min")
            range_max = args.get("range_max")
            if range_min is not None or range_max is not None:
                variable_obj["range"] = {}
                if range_min is not None:
                    variable_obj["range"]["min"] = range_min
                if range_max is not None:
                    variable_obj["range"]["max"] = range_max

        # Add to unified variables list
        workflow_analysis["variables"].append(variable_obj)

        return {
            "success": True,
            "message": f"Added input variable '{name}' ({var_type})",
            "variable": variable_obj,
            "workflow_analysis": workflow_analysis,
        }


# Backwards compatibility alias
AddWorkflowInputTool = AddWorkflowVariableTool
