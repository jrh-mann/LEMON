"""List workflow variables tool.

Multi-workflow architecture:
- Uses current_workflow_id from session_state (implicit binding)
- Loads workflow from database
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..core import WorkflowTool, ToolParameter


class ListWorkflowVariablesTool(WorkflowTool):
    """List all workflow variables.
    
    Returns all variables available in the workflow, including:
    - User inputs (source='input') - values provided at execution time
    - Subprocess outputs (source='subprocess') - derived from subflow execution
    - Calculated values (source='calculated') - computed during execution
    
    Uses the current workflow from session state.
    """

    uses_validator = False

    name = "list_workflow_variables"
    description = (
        "Get all workflow variables. "
        "Returns ALL variables available in the workflow, including user inputs, "
        "subprocess outputs, and calculated values. "
        "Use this to see what variables can be referenced in decision conditions "
        "and output templates."
    )
    parameters = []

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        workflow_data, error = self._load_workflow(args, **kwargs)
        if error:
            return error
        workflow_id = workflow_data["workflow_id"]

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
