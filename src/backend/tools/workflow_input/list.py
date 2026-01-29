"""List workflow variables tool."""

from __future__ import annotations

from typing import Any, Dict, List

from ..core import Tool
from .helpers import ensure_workflow_analysis


class ListWorkflowVariablesTool(Tool):
    """List all workflow variables.
    
    Returns all variables available in the workflow, including:
    - User inputs (source='input') - values provided at execution time
    - Subprocess outputs (source='subprocess') - derived from subflow execution
    - Calculated values (source='calculated') - computed during execution
    """

    name = "list_workflow_variables"
    description = (
        "Get all workflow variables. Returns ALL variables available in the workflow, "
        "including user inputs, subprocess outputs, and calculated values. "
        "Use this to see what variables can be referenced in decision conditions "
        "and output templates."
    )
    parameters = []

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        workflow_analysis = ensure_workflow_analysis(session_state)
        
        # Get ALL variables from unified variables list
        all_variables: List[Dict[str, Any]] = workflow_analysis.get("variables", [])
        
        # Organize by source for clarity
        input_vars = [v for v in all_variables if v.get("source", "input") == "input"]
        derived_vars = [v for v in all_variables if v.get("source", "input") != "input"]

        return {
            "success": True,
            "variables": all_variables,
            "count": len(all_variables),
            "input_count": len(input_vars),
            "derived_count": len(derived_vars),
            "workflow_analysis": workflow_analysis,
        }
