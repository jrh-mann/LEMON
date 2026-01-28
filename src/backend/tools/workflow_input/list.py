"""List workflow variables tool."""

from __future__ import annotations

from typing import Any, Dict

from ..core import Tool
from .helpers import ensure_workflow_analysis, get_input_variables


class ListWorkflowVariablesTool(Tool):
    """List all registered workflow input variables.
    
    Returns all variables with source='input' - these are the variables
    that users provide values for at execution time.
    """

    name = "list_workflow_variables"
    aliases = ["list_workflow_inputs"]  # Backwards compatibility
    description = (
        "Get all registered workflow input variables. Returns the list of input variables "
        "that have been registered with add_workflow_variable. These are variables that users "
        "provide values for at execution time. Use this to see what inputs are available "
        "before referencing them in nodes."
    )
    parameters = []

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        workflow_analysis = ensure_workflow_analysis(session_state)
        
        # Get input variables (source='input') from unified variables list
        input_variables = get_input_variables(workflow_analysis)

        return {
            "success": True,
            "inputs": input_variables,  # Backwards-compatible key name in response
            "variables": input_variables,  # New key name
            "count": len(input_variables),
            "workflow_analysis": workflow_analysis,
        }


# Backwards compatibility alias
ListWorkflowInputsTool = ListWorkflowVariablesTool
