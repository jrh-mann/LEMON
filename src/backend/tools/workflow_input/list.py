"""List workflow variables tool.

Multi-workflow architecture:
- Requires workflow_id parameter (workflow must exist in library)
- Loads workflow from database
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..core import Tool, ToolParameter
from ..workflow_edit.helpers import load_workflow_for_tool


class ListWorkflowVariablesTool(Tool):
    """List all workflow variables.
    
    Returns all variables available in the workflow, including:
    - User inputs (source='input') - values provided at execution time
    - Subprocess outputs (source='subprocess') - derived from subflow execution
    - Calculated values (source='calculated') - computed during execution
    
    Requires workflow_id - the workflow must exist in the library first.
    """

    name = "list_workflow_variables"
    description = (
        "Get all workflow variables. Requires workflow_id. "
        "Returns ALL variables available in the workflow, including user inputs, "
        "subprocess outputs, and calculated values. "
        "Use this to see what variables can be referenced in decision conditions "
        "and output templates."
    )
    parameters = [
        # workflow_id is REQUIRED and must be first
        ToolParameter(
            "workflow_id",
            "string",
            "ID of the workflow to list variables from (from create_workflow)",
            required=True,
        ),
    ]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        workflow_id = args.get("workflow_id")

        # Load workflow from database
        workflow_data, error = load_workflow_for_tool(workflow_id, session_state)
        if error:
            return error

        # Get ALL variables from loaded workflow
        all_variables: List[Dict[str, Any]] = workflow_data["variables"]
        
        # Organize by source for clarity
        input_vars = [v for v in all_variables if v.get("source", "input") == "input"]
        derived_vars = [v for v in all_variables if v.get("source", "input") != "input"]

        return {
            "success": True,
            "workflow_id": workflow_id,
            "variables": all_variables,
            "count": len(all_variables),
            "input_count": len(input_vars),
            "derived_count": len(derived_vars),
        }
