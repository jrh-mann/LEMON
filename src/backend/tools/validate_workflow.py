"""Validate workflow tool."""

from __future__ import annotations

from typing import Any, Dict

from ..validation.workflow_validator import WorkflowValidator
from .core import Tool


class ValidateWorkflowTool(Tool):
    """Validate the current workflow structure."""

    name = "validate_workflow"
    description = "Validate the workflow for structural correctness, including reachability and disconnected nodes."
    parameters = []

    def __init__(self):
        self.validator = WorkflowValidator()

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        current_workflow = session_state.get("current_workflow", {"nodes": [], "edges": []})
        
        # Get variables from unified 'variables' field
        workflow_analysis = session_state.get("workflow_analysis", {})
        variables = workflow_analysis.get("variables", [])
        
        workflow_to_validate = {
            "nodes": current_workflow.get("nodes", []),
            "edges": current_workflow.get("edges", []),
            "variables": variables,
        }
        
        # Use strict=True to check for unreachable nodes and complete structure
        is_valid, errors = self.validator.validate(workflow_to_validate, strict=True)
        
        if is_valid:
            return {
                "success": True,
                "valid": True,
                "message": "Workflow is valid. All nodes are reachable and connected correctly.",
            }
        else:
            error_message = self.validator.format_errors(errors)
            return {
                "success": True,
                "valid": False,
                "errors": [
                    {"code": e.code, "message": e.message, "node_id": e.node_id}
                    for e in errors
                ],
                "message": error_message,
            }
