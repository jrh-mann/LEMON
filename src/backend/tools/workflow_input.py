"""Tools for managing workflow inputs (parameters that users provide at runtime)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .core import Tool, ToolParameter


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
        """Add input to workflow_analysis.inputs."""
        session_state = kwargs.get("session_state", {})

        # Ensure workflow_analysis exists
        if "workflow_analysis" not in session_state:
            session_state["workflow_analysis"] = {"inputs": [], "outputs": []}

        workflow_analysis = session_state["workflow_analysis"]
        if "inputs" not in workflow_analysis:
            workflow_analysis["inputs"] = []

        # Validate required fields
        name = args.get("name")
        input_type = args.get("type")

        if not name or not isinstance(name, str) or not name.strip():
            return {"success": False, "error": "Input 'name' is required and must be a non-empty string"}

        if not input_type or input_type not in ["string", "number", "boolean", "enum"]:
            return {
                "success": False,
                "error": "Input 'type' must be one of: string, number, boolean, enum"
            }

        # Validate enum type has values
        if input_type == "enum":
            enum_values = args.get("enum_values")
            if not enum_values or not isinstance(enum_values, list) or len(enum_values) == 0:
                return {
                    "success": False,
                    "error": "enum_values is required for type 'enum' and must be a non-empty array"
                }

        # Check for duplicate (case-insensitive)
        normalized_name = name.strip().lower()
        existing_inputs = workflow_analysis["inputs"]
        for existing in existing_inputs:
            if existing.get("name", "").strip().lower() == normalized_name:
                return {
                    "success": False,
                    "error": f"Input '{name}' already exists (case-insensitive check)"
                }

        # Build input object
        input_obj = {
            "name": name.strip(),
            "type": input_type,
        }

        # Optional fields
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

        # Add to workflow_analysis
        workflow_analysis["inputs"].append(input_obj)

        return {
            "success": True,
            "message": f"Added input '{name}' ({input_type})",
            "input": input_obj,
            # Return full workflow_analysis for MCP synchronization
            "workflow_analysis": workflow_analysis,
        }


class ListWorkflowInputsTool(Tool):
    """List all registered workflow inputs."""

    name = "list_workflow_inputs"
    description = (
        "Get all registered workflow inputs. Returns the list of inputs that have been "
        "registered with add_workflow_input. Use this to see what inputs are available "
        "before referencing them in nodes."
    )
    parameters = []

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        """Return all inputs from workflow_analysis."""
        session_state = kwargs.get("session_state", {})

        # Ensure workflow_analysis exists
        if "workflow_analysis" not in session_state:
            session_state["workflow_analysis"] = {"inputs": [], "outputs": []}

        workflow_analysis = session_state["workflow_analysis"]
        inputs = workflow_analysis.get("inputs", [])

        return {
            "success": True,
            "inputs": inputs,
            "count": len(inputs),
            # Return full workflow_analysis for MCP synchronization
            "workflow_analysis": workflow_analysis,
        }


class RemoveWorkflowInputTool(Tool):
    """Remove a registered workflow input."""

    name = "remove_workflow_input"
    description = (
        "Remove a registered workflow input by name (case-insensitive). "
        "Note: This does NOT remove input_ref from nodes that reference it - "
        "you should check if nodes reference this input first."
    )
    parameters = [
        ToolParameter(
            "name",
            "string",
            "Name of the input to remove (case-insensitive)",
            required=True,
        ),
    ]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        """Remove input from workflow_analysis.inputs."""
        session_state = kwargs.get("session_state", {})

        # Ensure workflow_analysis exists
        if "workflow_analysis" not in session_state:
            session_state["workflow_analysis"] = {"inputs": [], "outputs": []}

        workflow_analysis = session_state["workflow_analysis"]
        inputs = workflow_analysis.get("inputs", [])

        name = args.get("name")
        if not name or not isinstance(name, str):
            return {"success": False, "error": "Input 'name' is required"}

        # Find and remove (case-insensitive)
        normalized_name = name.strip().lower()
        original_length = len(inputs)

        workflow_analysis["inputs"] = [
            inp for inp in inputs
            if inp.get("name", "").strip().lower() != normalized_name
        ]

        if len(workflow_analysis["inputs"]) == original_length:
            return {
                "success": False,
                "error": f"Input '{name}' not found"
            }

        return {
            "success": True,
            "message": f"Removed input '{name}'",
            # Return full workflow_analysis for MCP synchronization
            "workflow_analysis": workflow_analysis,
        }
