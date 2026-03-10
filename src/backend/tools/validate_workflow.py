"""Validate workflow tool.

Multi-workflow architecture:
- Uses current_workflow_id from session_state (implicit binding)
- Loads workflow from database
- Performs structural validation
"""

from __future__ import annotations

from typing import Any, Dict

from .core import WorkflowTool, ToolParameter


class ValidateWorkflowTool(WorkflowTool):
    """Validate the workflow structure.

    Uses the current workflow from session state.
    """

    name = "validate_workflow"
    description = (
        "Check if the active workflow is valid. "
        "Reports errors like disconnected nodes, missing branches, or unreachable paths. "
        "Use this when the user asks to validate, check, or verify the workflow."
    )
    parameters = []

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        workflow_data, error = self._load_workflow(args, **kwargs)
        if error:
            return error
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
