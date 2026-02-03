"""Tool for listing workflows in user's library."""

from __future__ import annotations

from typing import Any, Dict, List, Set

from ..core import Tool


class ListWorkflowsInLibrary(Tool):
    """List all workflows saved in the user's library.

    This tool allows the orchestrator to view workflows that the user has
    previously saved, including their metadata (name, description, domain, tags).
    
    Also includes all open tabs with unsaved workflows (drafts), so the LLM can
    see what the user is currently working on across all tabs.
    
    Useful for:
    - Discovering existing workflows before creating duplicates
    - Recommending relevant workflows to users
    - Understanding what domains/topics the user works with
    - Seeing all open unsaved workflows (drafts) across tabs
    - Getting the ID of the current workflow (even if unsaved)
    """

    @property
    def name(self) -> str:
        return "list_workflows_in_library"

    @property
    def description(self) -> str:
        return (
            "List all workflows saved in the user's library, plus any open unsaved workflows "
            "(drafts) from all tabs. Returns workflow metadata including name, description, "
            "domain, tags, validation status, and input/output information. "
            "Open drafts appear with status 'draft' or 'current (unsaved)' for the active tab. "
            "Use this to see all workflows the user has, including work in progress."
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
                - limit: Maximum workflows to return
            **kwargs: Additional arguments including session_state

        Returns:
            Dict with:
                - success: bool
                - workflows: list of workflow summaries with status indicator
                - count: total number of workflows
                - current_workflow_id: ID of the current canvas workflow (if any)
                - message: human-readable result
        """
        # Extract parameters from args
        search_query = args.get("search_query")
        domain = args.get("domain")
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

        # Get current workflow info (the active tab)
        current_workflow_id = session_state.get("current_workflow_id")
        
        # Get all open tabs with workflows (for showing drafts from other tabs)
        open_tabs: List[Dict[str, Any]] = session_state.get("open_tabs", [])

        try:
            # Search or list workflows from DB (all are "saved", no draft filtering)
            if search_query or domain:
                workflows, total_count = workflow_store.search_workflows(
                    user_id,
                    query=search_query,
                    domain=domain,
                    limit=limit,
                    offset=0,
                )
            else:
                workflows, total_count = workflow_store.list_workflows(
                    user_id,
                    limit=limit,
                    offset=0,
                )

            # Format workflows for output with status indicator
            workflow_summaries = []
            
            # Track which workflow IDs are in the DB (to identify unsaved drafts)
            db_workflow_ids: Set[str] = {wf.id for wf in workflows}
            
            # Add open tabs that are NOT saved in DB (drafts/unsaved workflows)
            # These appear first so the LLM sees them prominently
            draft_count = 0
            for tab in open_tabs:
                tab_workflow_id = tab.get("workflow_id")
                if not tab_workflow_id:
                    continue
                    
                # Skip if this workflow is already saved in DB
                if tab_workflow_id in db_workflow_ids:
                    continue
                
                # This is an unsaved draft - add it to the list
                is_active = tab.get("is_active", False)
                status = "current (unsaved)" if is_active else "draft"
                
                workflow_summaries.append({
                    "id": tab_workflow_id,
                    "name": tab.get("title", "(Untitled Draft)"),
                    "description": "Unsaved workflow in an open tab" if not is_active else "The workflow currently on the canvas (not yet saved)",
                    "domain": None,
                    "tags": [],
                    "input_names": [],
                    "output_values": [],
                    "is_validated": False,
                    "validation_score": 0,
                    "validation_count": 0,
                    "status": status,
                    "is_current": is_active,
                    "is_draft": True,
                    "node_count": tab.get("node_count", 0),
                    "edge_count": tab.get("edge_count", 0),
                    "created_at": None,
                    "updated_at": None,
                })
                draft_count += 1

            # Add DB workflows
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

                # Determine status: "current" if this is the active workflow, else "saved"
                is_current = current_workflow_id and wf.id == current_workflow_id
                status = "current" if is_current else "saved"

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
                    "status": status,
                    "is_current": is_current,
                    "is_draft": False,
                    "created_at": wf.created_at,
                    "updated_at": wf.updated_at,
                })

            # Build message
            db_count = total_count
            display_count = db_count + draft_count
            
            if display_count == 0:
                message = "No workflows found in library."
                if search_query:
                    message += f" Search query: '{search_query}'"
                if domain:
                    message += f" Domain filter: '{domain}'"
            elif display_count == 1:
                if draft_count == 1:
                    message = "Found 1 workflow: unsaved draft"
                else:
                    message = f"Found 1 workflow: {workflows[0].name}"
            else:
                parts = []
                if draft_count > 0:
                    parts.append(f"{draft_count} unsaved draft{'s' if draft_count > 1 else ''}")
                if db_count > 0:
                    parts.append(f"{db_count} saved")
                message = f"Found {display_count} workflows ({', '.join(parts)})"
                if search_query:
                    message += f" matching '{search_query}'"
                if domain:
                    message += f" in domain '{domain}'"

            return {
                "success": True,
                "workflows": workflow_summaries,
                "count": display_count,
                "db_count": db_count,
                "draft_count": draft_count,
                "current_workflow_id": current_workflow_id,
                "message": message,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to list workflows: {str(e)}",
            }
