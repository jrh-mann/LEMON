"""Tool for listing workflows in user's library."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..core import Tool


class ListWorkflowsInLibrary(Tool):
    """List all workflows saved in the user's library.

    This tool allows the orchestrator to view workflows that the user has
    previously saved, including their metadata (name, description, domain, tags).
    Useful for:
    - Discovering existing workflows before creating duplicates
    - Recommending relevant workflows to users
    - Understanding what domains/topics the user works with
    """

    @property
    def name(self) -> str:
        return "list_workflows_in_library"

    @property
    def description(self) -> str:
        return (
            "List all workflows saved in the user's library. "
            "Returns workflow metadata including name, description, domain, tags, "
            "validation status, and input/output information. "
            "Use this to check if similar workflows already exist before creating new ones."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "search_query": {
                    "type": "string",
                    "description": "Optional text to search for in workflow names, descriptions, or domains",
                },
                "domain": {
                    "type": "string",
                    "description": "Optional domain filter (e.g., 'Healthcare', 'Finance')",
                },
                "include_drafts": {
                    "type": "boolean",
                    "description": "Include draft (unsaved) workflows. Default: true. Drafts are workflows created by the LLM but not yet saved to the user's library.",
                },
                "drafts_only": {
                    "type": "boolean",
                    "description": "Only return draft workflows. Default: false. Use this to see only unsaved workflows.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of workflows to return (default: 50, max: 100)",
                    "minimum": 1,
                    "maximum": 100,
                },
            },
            "required": [],
        }

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        """Execute the list_workflows_in_library tool.

        Args:
            args: Tool arguments containing:
                - search_query: Optional text search filter
                - domain: Optional domain filter
                - include_drafts: Include draft workflows (default: True)
                - drafts_only: Only return draft workflows (default: False)
                - limit: Maximum workflows to return
            **kwargs: Additional arguments including session_state

        Returns:
            Dict with:
                - success: bool
                - workflows: list of workflow summaries with status indicator
                - count: total number of workflows
                - message: human-readable result
        """
        # Extract parameters from args
        search_query = args.get("search_query")
        domain = args.get("domain")
        include_drafts = args.get("include_drafts", True)  # Default True for LLM use
        drafts_only = args.get("drafts_only", False)
        limit = args.get("limit", 50)

        # Get session_state from kwargs
        session_state = kwargs.get("session_state", {})
        # Validate session state
        if not session_state:
            return {
                "success": False,
                "error": "No session state provided",
                "message": "Unable to access workflow library - no session context. This tool requires direct mode (MCP mode not supported).",
            }

        workflow_store = session_state.get("workflow_store")
        user_id = session_state.get("user_id")

        if not workflow_store:
            return {
                "success": False,
                "error": "No workflow_store in session",
                "message": "Unable to access workflow library - storage not available. This tool requires direct mode (not MCP mode).",
            }

        if not user_id:
            return {
                "success": False,
                "error": "No user_id in session",
                "message": "Unable to access workflow library - user not authenticated. Please ensure user is logged in.",
            }

        # Clamp limit to valid range
        limit = max(1, min(limit, 100))

        try:
            # Search or list workflows with draft filtering
            if search_query or domain:
                workflows, total_count = workflow_store.search_workflows(
                    user_id,
                    query=search_query,
                    domain=domain,
                    include_drafts=include_drafts,
                    drafts_only=drafts_only,
                    limit=limit,
                    offset=0,
                )
            else:
                workflows, total_count = workflow_store.list_workflows(
                    user_id,
                    include_drafts=include_drafts,
                    drafts_only=drafts_only,
                    limit=limit,
                    offset=0,
                )

            # Format workflows for output with status indicator
            workflow_summaries = []
            for wf in workflows:
                # Extract input names
                input_names = [
                    inp.get("name", "")
                    for inp in wf.inputs
                    if isinstance(inp, dict)
                ]

                # Extract output values/names
                output_values = [
                    out.get("value", "") or out.get("name", "")
                    for out in wf.outputs
                    if isinstance(out, dict)
                ]

                # Status indicator: "saved" or "draft (unsaved)"
                status = "draft (unsaved)" if wf.is_draft else "saved"

                workflow_summaries.append({
                    "id": wf.id,
                    "name": wf.name,
                    "description": wf.description,
                    "domain": wf.domain,
                    "tags": wf.tags,
                    "input_names": input_names,
                    "output_values": output_values,
                    "is_validated": wf.is_validated,
                    "validation_score": wf.validation_score,
                    "validation_count": wf.validation_count,
                    "status": status,  # "saved" or "draft (unsaved)"
                    "is_draft": wf.is_draft,  # Raw bool for programmatic use
                    "created_at": wf.created_at,
                    "updated_at": wf.updated_at,
                })

            # Build message
            if total_count == 0:
                message = "No workflows found in library."
                if search_query:
                    message += f" Search query: '{search_query}'"
                if domain:
                    message += f" Domain filter: '{domain}'"
                if drafts_only:
                    message += " (drafts only)"
            elif total_count == 1:
                status_str = " (draft)" if workflows[0].is_draft else ""
                message = f"Found 1 workflow: {workflows[0].name}{status_str}"
            else:
                shown = min(limit, total_count)
                # Count drafts vs saved
                draft_count = sum(1 for wf in workflows if wf.is_draft)
                saved_count = len(workflows) - draft_count
                message = f"Found {total_count} workflows (showing {shown}: {saved_count} saved, {draft_count} drafts)"
                if search_query:
                    message += f" matching '{search_query}'"
                if domain:
                    message += f" in domain '{domain}'"

            return {
                "success": True,
                "workflows": workflow_summaries,
                "count": total_count,
                "shown": len(workflow_summaries),
                "message": message,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to list workflows: {str(e)}",
            }
