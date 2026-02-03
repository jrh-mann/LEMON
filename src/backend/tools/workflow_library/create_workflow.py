"""Tool for creating a new workflow in the user's library.

This tool creates a new workflow entry in the database with an empty
structure. The workflow must be created before any editing tools can
operate on it - this ensures every tool call has a valid workflow_id
and all changes are auto-persisted.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict

from ..core import Tool, ToolParameter


# Valid output types for workflows
VALID_OUTPUT_TYPES = frozenset({"string", "int", "float", "bool", "json"})


def generate_workflow_id() -> str:
    """Generate a unique workflow ID.
    
    Format: wf_{8_hex_chars} for readability and uniqueness.
    """
    return f"wf_{uuid.uuid4().hex[:8]}"


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
            "Type of value the workflow returns: 'string', 'int', 'float', 'bool', or 'json'",
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
        if not output_type or output_type not in VALID_OUTPUT_TYPES:
            return {
                "success": False,
                "error": f"Workflow 'output_type' must be one of: {', '.join(sorted(VALID_OUTPUT_TYPES))}",
                "error_code": "INVALID_OUTPUT_TYPE",
            }
        
        # Get session state
        session_state = kwargs.get("session_state", {})
        if not session_state:
            return {
                "success": False,
                "error": "No session state provided",
                "error_code": "NO_SESSION",
                "message": "Unable to create workflow - no session context.",
            }
        
        workflow_store = session_state.get("workflow_store")
        user_id = session_state.get("user_id")
        
        if not workflow_store:
            return {
                "success": False,
                "error": "No workflow_store in session",
                "error_code": "NO_STORE",
                "message": "Unable to create workflow - storage not available.",
            }
        
        if not user_id:
            return {
                "success": False,
                "error": "No user_id in session",
                "error_code": "NO_USER",
                "message": "Unable to create workflow - user not authenticated.",
            }
        
        # Extract optional parameters
        description = args.get("description", "")
        domain = args.get("domain")
        tags = args.get("tags", [])
        
        # Validate tags is a list
        if tags and not isinstance(tags, list):
            tags = [str(tags)]
        
        # Generate unique workflow ID
        workflow_id = generate_workflow_id()
        
        try:
            # Create workflow in database with empty structure
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
