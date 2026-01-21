"""Add workflow input tool."""

from __future__ import annotations

from typing import Any, Dict

from ..core import Tool, ToolParameter
from .helpers import ensure_workflow_analysis, normalize_input_name


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

        input_obj = {
            "name": name.strip(),
            "type": input_type,
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
