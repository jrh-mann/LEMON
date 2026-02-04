"""Add workflow variable tool.

This tool registers user-input variables for the workflow. These are variables
that users provide values for at execution time. For subprocess outputs or
calculated variables, those are created automatically when adding nodes.

Multi-workflow architecture:
- Requires workflow_id parameter (workflow must exist in library)
- Loads workflow from database at start
- Auto-saves changes back to database when done
"""

from __future__ import annotations

import re
from typing import Any, Dict

from ..core import Tool, ToolParameter
from ..workflow_edit.helpers import load_workflow_for_tool, save_workflow_changes
from .helpers import normalize_variable_name


# Map user-friendly types to internal types used by condition validation
# and the execution interpreter. 'number' is now a unified numeric type
# that supports both integers and floats (stored as float internally).
USER_TYPE_TO_INTERNAL = {
    "string": "string",
    "number": "number",  # Unified numeric type (stored as float)
    "boolean": "bool",
    "enum": "enum",
}


def generate_variable_id(name: str, internal_type: str, source: str = "input") -> str:
    """Generate deterministic variable ID from name, type, and source.
    
    Format: var_{slug}_{type} for inputs, or var_{source}_{slug}_{type} for derived
    
    Args:
        name: Variable name (e.g., "Patient Age")
        internal_type: Internal type (e.g., "number", "bool", "string")
        source: Variable source ("input", "subprocess", "calculated", "constant")
        
    Returns:
        Variable ID (e.g., "var_patient_age_number", "var_sub_creditscore_number")
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
    
    Requires workflow_id - the workflow must exist in the library first.
    """

    name = "add_workflow_variable"
    aliases = ["add_workflow_input"]  # Backwards compatibility
    description = (
        "Register an input variable for the workflow. Requires workflow_id. "
        "This variable will appear in the Variables tab where users can provide values at execution time. "
        "Use this when the workflow needs data from users (e.g., 'Patient Age', 'Email Address', 'Order Amount'). "
        "For subprocess outputs, use the output_variable parameter when adding a subprocess node instead."
    )
    parameters = [
        # workflow_id is REQUIRED and must be first
        ToolParameter(
            "workflow_id",
            "string",
            "ID of the workflow to add the variable to (from create_workflow)",
            required=True,
        ),
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
        workflow_id = args.get("workflow_id")

        # Load workflow from database (will fallback to current_workflow_id from session)
        workflow_data, error = load_workflow_for_tool(workflow_id, session_state)
        if error:
            return error
        
        # Use the workflow_id from loaded data (handles fallback to current_workflow_id)
        workflow_id = workflow_data["workflow_id"]

        # Extract variables from loaded workflow
        variables = list(workflow_data["variables"])

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
        for existing in variables:
            if normalize_variable_name(existing.get("name", "")) == normalized_name:
                return {
                    "success": False,
                    "error": f"Variable '{name}' already exists (case-insensitive check)"
                }

        # Map user-friendly type to internal type
        internal_type = USER_TYPE_TO_INTERNAL.get(var_type, "string")
        
        # For number type, always use 'number' (unified numeric type)
        
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

        # Add to variables list
        variables.append(variable_obj)

        # Auto-save changes to database
        save_error = save_workflow_changes(workflow_id, session_state, variables=variables)
        if save_error:
            return save_error

        return {
            "success": True,
            "workflow_id": workflow_id,
            "message": f"Added input variable '{name}' ({var_type}) to workflow {workflow_id}",
            "variable": variable_obj,
            # Return workflow_analysis for orchestrator to sync local state
            "workflow_analysis": {"variables": variables},
        }
