"""Set workflow output tool.

This tool allows declaring the workflow's output with a required type.
The output type is critical for subprocess variable inference - when another
workflow calls this one as a subprocess, the output type determines the type
of the derived variable.

Multi-workflow architecture:
- Requires workflow_id parameter (workflow must exist in library)
- Loads workflow from database at start
- Auto-saves changes back to database when done
"""

from __future__ import annotations

from typing import Any, Dict

from ..core import Tool, ToolParameter
from ..workflow_edit.helpers import load_workflow_for_tool, save_workflow_changes


# Valid output types that can be declared
VALID_OUTPUT_TYPES = {"string", "number", "bool", "enum", "date"}


class SetWorkflowOutputTool(Tool):
    """Set the workflow's output definition including its type.
    
    The output type is required for subprocess variable inference. When this
    workflow is used as a subprocess, the calling workflow needs to know what
    type of value to expect.
    
    Requires workflow_id - the workflow must exist in the library first.
    """

    name = "set_workflow_output"
    description = (
        "Declare the workflow's output with a name, type, and optional description. "
        "Requires workflow_id. "
        "The output type is REQUIRED and determines the type of the derived variable "
        "when this workflow is called as a subprocess. Common types: string, int, float, bool."
    )
    parameters = [
        # workflow_id is REQUIRED and must be first
        ToolParameter(
            "workflow_id",
            "string",
            "ID of the workflow to set output for (from create_workflow)",
            required=True,
        ),
        ToolParameter(
            "name",
            "string",
            "Name of the output (e.g., 'BMI Result', 'Credit Score', 'Risk Level')",
            required=True,
        ),
        ToolParameter(
            "type",
            "string",
            "Output type: 'string', 'number', 'bool', 'enum', or 'date'. This is REQUIRED.",
            required=True,
        ),
        ToolParameter(
            "description",
            "string",
            "Optional description of what this output represents",
            required=False,
        ),
    ]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        workflow_id = args.get("workflow_id")

        # Load workflow from database
        workflow_data, error = load_workflow_for_tool(workflow_id, session_state)
        if error:
            return error

        # Extract outputs from loaded workflow
        outputs = list(workflow_data["outputs"])

        name = args.get("name")
        output_type = args.get("type")
        description = args.get("description")

        # Validate name
        if not name or not isinstance(name, str) or not name.strip():
            return {
                "success": False,
                "error": "Output 'name' is required and must be a non-empty string"
            }

        # Validate type is provided and valid
        if not output_type:
            return {
                "success": False,
                "error": "Output 'type' is required. Valid types: string, int, float, bool, enum, date"
            }
        
        if output_type not in VALID_OUTPUT_TYPES:
            return {
                "success": False,
                "error": f"Invalid output type '{output_type}'. Valid types: {', '.join(sorted(VALID_OUTPUT_TYPES))}"
            }

        # Create output definition with required type
        output_def: Dict[str, Any] = {
            "name": name.strip(),
            "type": output_type,
        }
        
        if description:
            output_def["description"] = description

        # Check if an output with this name already exists and update it
        normalized_name = name.strip().lower()
        found = False
        
        for i, existing in enumerate(outputs):
            if existing.get("name", "").strip().lower() == normalized_name:
                # Update existing output
                outputs[i] = output_def
                found = True
                break
        
        if not found:
            # Add new output
            outputs.append(output_def)

        # Auto-save changes to database
        save_error = save_workflow_changes(workflow_id, session_state, outputs=outputs)
        if save_error:
            return save_error

        action = "Updated" if found else "Set"
        return {
            "success": True,
            "workflow_id": workflow_id,
            "message": f"{action} workflow output '{name}' (type: {output_type}) for workflow {workflow_id}",
            "output": output_def,
        }
