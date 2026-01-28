"""Modify workflow variable tool.

This tool allows modifying existing variables, including derived variables
from subprocess nodes. This is essential when the automatically inferred
type is incorrect or needs adjustment.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from ..core import Tool, ToolParameter
from .helpers import ensure_workflow_analysis, normalize_variable_name
from .add import generate_variable_id


# Valid internal types for variables
VALID_TYPES = {"string", "int", "float", "bool", "enum", "date"}

# Map user-friendly types to internal types
USER_TYPE_TO_INTERNAL = {
    "string": "string",
    "number": "float",
    "integer": "int",
    "boolean": "bool",
    "enum": "enum",
    "date": "date",
    # Also accept internal types directly
    "int": "int",
    "float": "float",
    "bool": "bool",
}


class ModifyWorkflowVariableTool(Tool):
    """Modify an existing workflow variable's properties.
    
    This tool can change the type, description, range, or enum values of any
    variable, including derived variables created by subprocess nodes. Use this
    when the auto-inferred type from a subprocess is incorrect.
    
    IMPORTANT: Changing a variable's type will update its ID (since IDs include
    the type). Any decision nodes referencing the old ID will need to be updated.
    """

    name = "modify_workflow_variable"
    aliases = ["modify_workflow_input"]  # Backwards compatibility
    description = (
        "Modify an existing workflow variable's properties (type, description, range, enum values). "
        "Use this to correct auto-inferred types for subprocess outputs. For example, if a subprocess "
        "output was inferred as 'string' but should be 'int', use this tool to fix it. "
        "NOTE: Changing the type will also update the variable ID."
    )
    parameters = [
        ToolParameter(
            "name",
            "string",
            "Name of the variable to modify (case-insensitive match)",
            required=True,
        ),
        ToolParameter(
            "new_type",
            "string",
            "New type: 'string', 'number', 'integer', 'boolean', 'enum', or 'date'. If not provided, type is unchanged.",
            required=False,
        ),
        ToolParameter(
            "new_name",
            "string",
            "New name for the variable. If not provided, name is unchanged.",
            required=False,
        ),
        ToolParameter(
            "description",
            "string",
            "New description. If not provided, description is unchanged.",
            required=False,
        ),
        ToolParameter(
            "enum_values",
            "array",
            "For enum type: array of allowed values. Required if changing to enum type.",
            required=False,
        ),
        ToolParameter(
            "range_min",
            "number",
            "For number/integer types: minimum allowed value",
            required=False,
        ),
        ToolParameter(
            "range_max",
            "number",
            "For number/integer types: maximum allowed value",
            required=False,
        ),
    ]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        workflow_analysis = ensure_workflow_analysis(session_state)

        name = args.get("name")
        new_type = args.get("new_type")
        new_name = args.get("new_name")
        description = args.get("description")
        enum_values = args.get("enum_values")
        range_min = args.get("range_min")
        range_max = args.get("range_max")

        # Validate name parameter
        if not name or not isinstance(name, str) or not name.strip():
            return {
                "success": False,
                "error": "Variable 'name' is required to identify which variable to modify"
            }

        # Validate new_type if provided
        if new_type:
            internal_type = USER_TYPE_TO_INTERNAL.get(new_type)
            if not internal_type:
                return {
                    "success": False,
                    "error": f"Invalid type '{new_type}'. Valid types: string, number, integer, boolean, enum, date"
                }
            
            # Enum requires enum_values
            if internal_type == "enum" and not enum_values:
                return {
                    "success": False,
                    "error": "enum_values is required when changing type to 'enum'"
                }

        # Find the variable by name (case-insensitive)
        variables = workflow_analysis.get("variables", [])
        normalized_name = normalize_variable_name(name)
        
        target_var = None
        target_idx = None
        for idx, var in enumerate(variables):
            if normalize_variable_name(var.get("name", "")) == normalized_name:
                target_var = var
                target_idx = idx
                break

        if target_var is None:
            # List available variables for helpful error message
            available = [v.get("name", "?") for v in variables]
            return {
                "success": False,
                "error": f"Variable '{name}' not found. Available variables: {available}"
            }

        # Track what changed for the message
        changes = []
        old_id = target_var["id"]
        old_type = target_var.get("type", "string")
        source = target_var.get("source", "input")

        # Update name if provided
        final_name = target_var["name"]
        if new_name and new_name.strip() and new_name.strip() != target_var["name"]:
            # Check new name doesn't conflict with other variables
            new_normalized = normalize_variable_name(new_name)
            for idx, var in enumerate(variables):
                if idx != target_idx and normalize_variable_name(var.get("name", "")) == new_normalized:
                    return {
                        "success": False,
                        "error": f"Variable name '{new_name}' already exists"
                    }
            final_name = new_name.strip()
            changes.append(f"name: '{target_var['name']}' -> '{final_name}'")
            target_var["name"] = final_name

        # Update type if provided
        final_type = old_type
        if new_type:
            internal_type = USER_TYPE_TO_INTERNAL.get(new_type, new_type)
            if internal_type != old_type:
                changes.append(f"type: '{old_type}' -> '{internal_type}'")
                final_type = internal_type
                target_var["type"] = internal_type

        # Regenerate ID if name or type changed
        if final_name != target_var.get("name") or final_type != old_type or new_name:
            new_id = generate_variable_id(final_name, final_type, source)
            if new_id != old_id:
                changes.append(f"id: '{old_id}' -> '{new_id}'")
                target_var["id"] = new_id

        # Update description if provided
        if description is not None:
            if description != target_var.get("description", ""):
                changes.append("description updated")
            target_var["description"] = description

        # Update enum_values if provided
        if enum_values is not None:
            if not isinstance(enum_values, list):
                return {"success": False, "error": "enum_values must be an array"}
            if final_type == "enum" and len(enum_values) == 0:
                return {"success": False, "error": "enum_values cannot be empty for enum type"}
            target_var["enum_values"] = enum_values
            changes.append(f"enum_values: {enum_values}")

        # Update range if provided
        if range_min is not None or range_max is not None:
            if final_type not in ("int", "float"):
                return {
                    "success": False,
                    "error": f"range_min/range_max only valid for number types, not '{final_type}'"
                }
            if "range" not in target_var:
                target_var["range"] = {}
            if range_min is not None:
                target_var["range"]["min"] = range_min
            if range_max is not None:
                target_var["range"]["max"] = range_max
            changes.append(f"range: [{range_min}, {range_max}]")

        # Update the variable in the list
        variables[target_idx] = target_var

        if not changes:
            return {
                "success": True,
                "message": f"No changes made to variable '{name}'",
                "variable": target_var,
                "workflow_analysis": workflow_analysis,
            }

        # Build warning about ID change if applicable
        warning = None
        if old_id != target_var["id"]:
            warning = (
                f"Variable ID changed from '{old_id}' to '{target_var['id']}'. "
                f"Any decision nodes using condition.input_id='{old_id}' must be updated."
            )

        result = {
            "success": True,
            "message": f"Modified variable '{final_name}': {', '.join(changes)}",
            "variable": target_var,
            "old_id": old_id,
            "new_id": target_var["id"],
            "workflow_analysis": workflow_analysis,
        }
        
        if warning:
            result["warning"] = warning

        return result


# Backwards compatibility alias
ModifyWorkflowInputTool = ModifyWorkflowVariableTool
