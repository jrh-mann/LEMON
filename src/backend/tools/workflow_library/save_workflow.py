"""Tool for saving a draft workflow to the user's library.

This tool publishes a draft workflow (is_draft=True) to the user's 
permanent library (is_draft=False). Drafts are workflows created by 
the LLM that haven't been explicitly saved by the user yet.
"""

from __future__ import annotations

from typing import Any, Dict

from ..core import Tool, ToolParameter


class SaveWorkflowToLibrary(Tool):
    """Save a draft workflow to the user's permanent library.
    
    When the LLM creates a workflow using create_workflow, it starts as
    a draft (is_draft=True). Drafts are visible to the LLM but not shown
    in the user's browse library. This tool publishes the draft to the
    user's permanent library by setting is_draft=False.
    
    Use this tool when:
    - The user explicitly asks to save the workflow
    - The workflow is complete and ready for use
    - The user wants to keep the workflow for future reference
    """

    name = "save_workflow_to_library"
    description = (
        "Save a draft workflow to the user's permanent library. Drafts are workflows "
        "you've created that haven't been saved yet. Once saved, the workflow will "
        "appear in the user's browse library. Use this when the user asks to save "
        "the workflow or confirms they want to keep it."
    )
    parameters = [
        ToolParameter(
            "workflow_id",
            "string",
            "The ID of the workflow to save (from create_workflow)",
            required=True,
        ),
        ToolParameter(
            "name",
            "string",
            "Optional new name for the workflow (updates existing name if provided)",
            required=False,
        ),
        ToolParameter(
            "description",
            "string",
            "Optional new description (updates existing if provided)",
            required=False,
        ),
        ToolParameter(
            "domain",
            "string",
            "Optional domain/category (updates existing if provided)",
            required=False,
        ),
        ToolParameter(
            "tags",
            "array",
            "Optional list of tags (updates existing if provided)",
            required=False,
        ),
    ]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        """Save a draft workflow to the user's library.
        
        Args:
            args: Tool arguments containing workflow_id and optional metadata updates
            **kwargs: Additional arguments including session_state
            
        Returns:
            Dict with success status and workflow info
        """
        # Validate required parameters
        workflow_id = args.get("workflow_id")
        if not workflow_id or not isinstance(workflow_id, str):
            return {
                "success": False,
                "error": "workflow_id is required",
                "error_code": "MISSING_WORKFLOW_ID",
            }
        
        # Get session state
        session_state = kwargs.get("session_state", {})
        if not session_state:
            return {
                "success": False,
                "error": "No session state provided",
                "error_code": "NO_SESSION",
                "message": "Unable to save workflow - no session context.",
            }
        
        workflow_store = session_state.get("workflow_store")
        user_id = session_state.get("user_id")
        
        if not workflow_store:
            return {
                "success": False,
                "error": "No workflow_store in session",
                "error_code": "NO_STORE",
                "message": "Unable to save workflow - storage not available.",
            }
        
        if not user_id:
            return {
                "success": False,
                "error": "No user_id in session",
                "error_code": "NO_USER",
                "message": "Unable to save workflow - user not authenticated.",
            }
        
        try:
            # First, verify the workflow exists and belongs to this user
            workflow = workflow_store.get_workflow(workflow_id, user_id)
            if not workflow:
                return {
                    "success": False,
                    "error": f"Workflow '{workflow_id}' not found",
                    "error_code": "NOT_FOUND",
                    "message": f"Cannot save workflow - no workflow with ID '{workflow_id}' exists.",
                }
            
            # Check if already saved (not a draft)
            if not workflow.is_draft:
                return {
                    "success": True,
                    "workflow_id": workflow_id,
                    "name": workflow.name,
                    "already_saved": True,
                    "message": f"Workflow '{workflow.name}' is already saved to the library.",
                }
            
            # Build update kwargs - always set is_draft=False
            update_kwargs: Dict[str, Any] = {"is_draft": False}
            
            # Include optional metadata updates if provided
            new_name = args.get("name")
            if new_name and isinstance(new_name, str) and new_name.strip():
                update_kwargs["name"] = new_name.strip()
            
            new_description = args.get("description")
            if new_description is not None:
                update_kwargs["description"] = new_description.strip() if new_description else ""
            
            new_domain = args.get("domain")
            if new_domain is not None:
                update_kwargs["domain"] = new_domain
            
            new_tags = args.get("tags")
            if new_tags is not None:
                if isinstance(new_tags, list):
                    update_kwargs["tags"] = new_tags
                else:
                    update_kwargs["tags"] = [str(new_tags)]
            
            # Update the workflow
            success = workflow_store.update_workflow(
                workflow_id,
                user_id,
                **update_kwargs,
            )
            
            if not success:
                return {
                    "success": False,
                    "error": "Failed to update workflow",
                    "error_code": "UPDATE_FAILED",
                    "message": "Unable to save workflow to library - update failed.",
                }
            
            # Get final name for response
            final_name = update_kwargs.get("name", workflow.name)
            
            return {
                "success": True,
                "workflow_id": workflow_id,
                "name": final_name,
                "already_saved": False,
                "message": f"Workflow '{final_name}' has been saved to the user's library. "
                           "It will now appear in their browse library.",
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "error_code": "SAVE_FAILED",
                "message": f"Failed to save workflow: {e}",
            }
