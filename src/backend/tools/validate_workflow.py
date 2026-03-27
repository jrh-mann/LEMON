"""Validate workflow tool.

Multi-workflow architecture:
- Uses current_workflow_id from session_state (implicit binding)
- Loads workflow from database
- Performs structural validation
"""

from __future__ import annotations

from typing import Any, Dict

from .core import WorkflowTool, ToolParameter


def _persist_validation_state(
    *,
    workflow_id: str,
    is_valid: bool,
    session_state: Dict[str, Any],
) -> Dict[str, Any] | None:
    workflow_store = session_state.get("workflow_store")
    user_id = session_state.get("user_id")

    if not workflow_store:
        return {
            "success": False,
            "error": "No workflow_store in session",
            "error_code": "NO_STORE",
            "message": "Unable to persist validation result - storage not available.",
        }
    if not user_id:
        return {
            "success": False,
            "error": "No user_id in session",
            "error_code": "NO_USER",
            "message": "Unable to persist validation result - user not authenticated.",
        }

    try:
        updated = workflow_store.update_workflow(
            workflow_id,
            user_id,
            is_validated=is_valid,
        )
    except Exception as exc:
        return {
            "success": False,
            "error": f"Failed to persist validation result: {exc}",
            "error_code": "DB_ERROR",
            "message": f"Failed to persist validation result for workflow '{workflow_id}'.",
        }

    if not updated:
        return {
            "success": False,
            "error": f"Workflow '{workflow_id}' not found",
            "error_code": "WORKFLOW_NOT_FOUND",
            "message": "Unable to persist validation result - workflow no longer exists.",
        }
    return None


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
        if workflow_data is None:
            return {
                "success": False,
                "error": "Failed to load workflow",
                "error_code": "WORKFLOW_LOAD_FAILED",
            }
        workflow_id = workflow_data["workflow_id"]
        session_state = kwargs.get("session_state", {})

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

        persist_error = _persist_validation_state(
            workflow_id=workflow_id,
            is_valid=is_valid,
            session_state=session_state,
        )
        if persist_error is not None:
            return persist_error

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
                    {"code": e.code, "message": e.message, "node_id": e.node_id} for e in errors
                ],
                "message": error_message,
            }
