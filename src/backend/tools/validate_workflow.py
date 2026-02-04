"""Validate workflow tool.

Multi-workflow architecture:
- Requires workflow_id parameter (workflow must exist in library)
- Loads workflow from database
- Performs structural validation
"""

from __future__ import annotations

from typing import Any, Dict

from ..validation.workflow_validator import WorkflowValidator
from .core import Tool, ToolParameter
from .workflow_edit.helpers import load_workflow_for_tool


class ValidateWorkflowTool(Tool):
    """Validate the workflow structure.
    
    Requires workflow_id - the workflow must exist in the library first.
    """

    name = "validate_workflow"
    description = (
        "Validate the workflow for structural correctness. Requires workflow_id. "
        "Checks reachability, disconnected nodes, decision node conditions, and more."
    )
    parameters = [
        # workflow_id is REQUIRED and must be first
        ToolParameter(
            "workflow_id",
            "string",
            "ID of the workflow to validate (from create_workflow)",
            required=True,
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
        # Use the workflow_id from loaded data (handles fallback to current_workflow_id)
        workflow_id = workflow_data["workflow_id"]

        # Build workflow dict for validation
        # Include output_type for Rule 14 validation (all end nodes must match workflow output_type)
        workflow_to_validate = {
            "nodes": workflow_data["nodes"],
            "edges": workflow_data["edges"],
            "variables": workflow_data["variables"],
            "output_type": workflow_data.get("output_type"),
        }
        
        # Use strict=True to check for unreachable nodes and complete structure
        is_valid, errors = self.validator.validate(workflow_to_validate, strict=True)
        
        if is_valid:
            return {
                "success": True,
                "workflow_id": workflow_id,
                "valid": True,
                "message": f"Workflow {workflow_id} is valid. All nodes are reachable and connected correctly.",
            }
        else:
            error_message = self.validator.format_errors(errors)
            return {
                "success": True,
                "workflow_id": workflow_id,
                "valid": False,
                "errors": [
                    {"code": e.code, "message": e.message, "node_id": e.node_id}
                    for e in errors
                ],
                "message": error_message,
            }
