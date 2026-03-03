"""Tool for creating a new workflow in the user's library.

This tool creates a new workflow entry in the database with an empty
structure. The workflow must be created before any editing tools can
operate on it - this ensures every tool call has a valid workflow_id
and all changes are auto-persisted.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict

from ..core import Tool, ToolParameter, extract_session_deps
from ..constants import VALID_WORKFLOW_OUTPUT_TYPES



def generate_workflow_id() -> str:
    """Generate a unique workflow ID.
    
    Format: wf_{32_hex_chars} — canonical format used by frontend, backend,
    and REST API. Uses full UUID4 hex for guaranteed uniqueness.
    """
    return f"wf_{uuid.uuid4().hex}"


class CreateWorkflowTool(Tool):
    """Create a new workflow in the user's library.
    
    This tool creates a new empty workflow that can then be edited using
    other workflow tools (add_node, add_connection, etc.). All workflows
    must be created via this tool before editing - there are no temporary
    or unsaved workflows.
    
    The output_type parameter declares what type of value the workflow
    will return when executed. All end nodes in the workflow must produce
    values compatible with this type.
    """

    name = "create_workflow"
    description = (
        "Create a new workflow in the user's library. Returns a workflow_id that must "
        "be used in all subsequent tool calls to edit this workflow. The workflow starts "
        "empty (no nodes or edges) and must be built using add_node, add_connection, etc. "
        "Always call this FIRST before adding nodes or variables to a workflow."
    )
    parameters = [
        ToolParameter(
            "name",
            "string",
            "Name for the workflow (e.g., 'BMI Calculator', 'Loan Approval')",
            required=True,
        ),
        ToolParameter(
            "description",
            "string",
            "Description of what the workflow does",
            required=False,
        ),
        ToolParameter(
            "output_type",
            "string",
            "Type of value the workflow returns: 'string', 'number', 'bool', or 'json'",
            required=True,
        ),
        ToolParameter(
            "domain",
            "string",
            "Domain/category for the workflow (e.g., 'Healthcare', 'Finance')",
            required=False,
        ),
        ToolParameter(
            "tags",
            "array",
            "List of tags for categorization",
            required=False,
        ),
    ]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        """Create a new workflow in the database.
        
        Args:
            args: Tool arguments containing name, description, output_type, etc.
            **kwargs: Additional arguments including session_state
            
        Returns:
            Dict with workflow_id on success, or error on failure
        """
        # Validate required parameters
        name = args.get("name")
        if not name or not isinstance(name, str) or not name.strip():
            return {
                "success": False,
                "error": "Workflow 'name' is required and must be a non-empty string",
                "error_code": "MISSING_NAME",
            }
        
        output_type = args.get("output_type")
        if not output_type or output_type not in VALID_WORKFLOW_OUTPUT_TYPES:
            return {
                "success": False,
                "error": f"Workflow 'output_type' must be one of: {', '.join(sorted(VALID_WORKFLOW_OUTPUT_TYPES))}",
                "error_code": "INVALID_OUTPUT_TYPE",
            }
        
        # Get session state and validate dependencies
        session_state, workflow_store, user_id, err = extract_session_deps(
            kwargs, action="create workflow",
        )
        if err:
            return err
        
        # Extract optional parameters
        description = args.get("description", "")
        domain = args.get("domain")
        tags = args.get("tags", [])
        
        # Validate tags is a list
        if tags and not isinstance(tags, list):
            tags = [str(tags)]
        
        # Use provided workflow_id from session if available (frontend generates ID on tab creation)
        # This ensures the canvas workflow and saved workflow share the same ID (no duplicates)
        candidate_id = session_state.get("current_workflow_id")
        if candidate_id:
            # Check if workflow with this ID already exists (e.g., auto-persisted from analysis)
            existing = workflow_store.get_workflow(candidate_id, user_id)
            if existing:
                # Workflow already exists — update its name/output_type instead of creating
                # a new empty one. This preserves variables/nodes from auto-persist.
                workflow_id = candidate_id
                try:
                    workflow_store.update_workflow(
                        workflow_id, user_id,
                        name=name.strip(),
                        output_type=output_type,
                    )
                    return {
                        "success": True,
                        "workflow_id": workflow_id,
                        "name": name.strip(),
                        "output_type": output_type,
                        "message": f"Updated workflow '{name.strip()}' ({workflow_id}). "
                                   f"Use this workflow_id in all subsequent tool calls.",
                    }
                except Exception as e:
                    return {
                        "success": False,
                        "error": str(e),
                        "error_code": "UPDATE_FAILED",
                        "message": f"Failed to update workflow: {e}",
                    }
            else:
                # ID is available - use it (saving canvas workflow for first time)
                workflow_id = candidate_id
        else:
            # No current_workflow_id - generate fresh ID
            workflow_id = generate_workflow_id()

        try:
            # Create workflow in database with empty structure
            # is_draft=False because all DB workflows are "saved" - they're in the user's library
            workflow_store.create_workflow(
                workflow_id=workflow_id,
                user_id=user_id,
                name=name.strip(),
                description=description.strip() if description else "",
                domain=domain,
                tags=tags,
                nodes=[],           # Start with empty nodes
                edges=[],           # Start with empty edges
                inputs=[],          # Start with empty variables (stored as 'inputs')
                outputs=[],         # Start with empty outputs
                tree={},
                doubts=[],
                validation_score=0,
                validation_count=0,
                is_validated=False,
                output_type=output_type,  # Store the declared output type
                is_draft=False,     # All DB workflows are saved (not drafts)
            )
            
            return {
                "success": True,
                "workflow_id": workflow_id,
                "name": name.strip(),
                "output_type": output_type,
                "message": f"Created workflow '{name.strip()}' with ID {workflow_id}. "
                           f"Use this workflow_id in all subsequent tool calls.",
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "error_code": "CREATE_FAILED",
                "message": f"Failed to create workflow: {e}",
            }
