"""Add workflow input tool."""

from __future__ import annotations

import re
from typing import Any, Dict

from ..core import Tool, ToolParameter
from .helpers import ensure_workflow_analysis, normalize_input_name


# Map user-friendly types to internal types used by condition validation
# and the execution interpreter. For 'number', we use 'float' as default
# since it's more general (accepts both integers and decimals).
USER_TYPE_TO_INTERNAL = {
    "string": "string",
    "number": "float",  # Use float for number type (more general)
    "boolean": "bool",
    "enum": "enum",
}


def generate_input_id(name: str, internal_type: str) -> str:
    """Generate deterministic input ID from name and type.
    
    Format: input_{slug}_{type}
    
    Args:
        name: Input name (e.g., "Patient Age")
        internal_type: Internal type (e.g., "int", "float", "bool", "string")
        
    Returns:
        Input ID (e.g., "input_patient_age_float")
    """
    # Slugify: lowercase, replace non-alphanumeric with underscore, strip trailing
    slug = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
    return f"input_{slug}_{internal_type}"


class AddWorkflowInputTool(Tool):
    """Register a workflow input that will appear in the Inputs tab."""

    name = "add_workflow_input"
    description = (
        "Register an input parameter for the workflow. This input will appear in the Inputs tab "
        "where users can provide values. Use this when the workflow needs data from users (e.g., "
        "'Patient Age', 'Email Address', 'Order Amount')."
    )
    parameters = [
        ToolParameter(
            "name",
            "string",
            "Human-readable input name (e.g., 'Patient Age', 'Email Address')",
            required=True,
        ),
        ToolParameter(
            "type",
            "string",
            "Input type: 'string', 'number', 'boolean', or 'enum'",
            required=True,
        ),
        ToolParameter(
            "description",
            "string",
            "Optional description of what this input represents",
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
        input_type = args.get("type")

        if not name or not isinstance(name, str) or not name.strip():
            return {"success": False, "error": "Input 'name' is required and must be a non-empty string"}

        if not input_type or input_type not in ["string", "number", "boolean", "enum"]:
            return {
                "success": False,
                "error": "Input 'type' must be one of: string, number, boolean, enum"
            }

        if input_type == "enum":
            enum_values = args.get("enum_values")
            if not enum_values or not isinstance(enum_values, list) or len(enum_values) == 0:
                return {
                    "success": False,
                    "error": "enum_values is required for type 'enum' and must be a non-empty array"
                }

        normalized_name = normalize_input_name(name)
        for existing in workflow_analysis["inputs"]:
            if normalize_input_name(existing.get("name", "")) == normalized_name:
                return {
                    "success": False,
                    "error": f"Input '{name}' already exists (case-insensitive check)"
                }

        # Map user-friendly type to internal type
        internal_type = USER_TYPE_TO_INTERNAL.get(input_type, "string")
        
        # For number type with range constraints, determine if int or float
        # based on whether min/max values are integers
        if input_type == "number":
            range_min = args.get("range_min")
            range_max = args.get("range_max")
            # If both range values are provided and both are integers, use int
            if range_min is not None and range_max is not None:
                if isinstance(range_min, int) and isinstance(range_max, int):
                    # Check they're not float-like (e.g., 5.0)
                    if range_min == int(range_min) and range_max == int(range_max):
                        internal_type = "int"
        
        # Generate deterministic ID
        input_id = generate_input_id(name.strip(), internal_type)

        input_obj = {
            "id": input_id,
            "name": name.strip(),
            "type": internal_type,  # Store internal type for condition validation
        }

        if args.get("description"):
            input_obj["description"] = args["description"]

        if input_type == "enum" and args.get("enum_values"):
            input_obj["enum_values"] = args["enum_values"]

        if input_type == "number":
            range_min = args.get("range_min")
            range_max = args.get("range_max")
            if range_min is not None or range_max is not None:
                input_obj["range"] = {}
                if range_min is not None:
                    input_obj["range"]["min"] = range_min
                if range_max is not None:
                    input_obj["range"]["max"] = range_max

        workflow_analysis["inputs"].append(input_obj)

        return {
            "success": True,
            "message": f"Added input '{name}' ({input_type})",
            "input": input_obj,
            "workflow_analysis": workflow_analysis,
        }
