"""List workflow inputs tool."""

from __future__ import annotations

from typing import Any, Dict

from ..core import Tool
from .helpers import ensure_workflow_analysis


class ListWorkflowInputsTool(Tool):
    """List all registered workflow inputs."""

    name = "list_workflow_inputs"
    description = (
        "Get all registered workflow inputs. Returns the list of inputs that have been "
        "registered with add_workflow_input. Use this to see what inputs are available "
        "before referencing them in nodes."
    )
    parameters = []

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        workflow_analysis = ensure_workflow_analysis(session_state)
        inputs = workflow_analysis.get("inputs", [])

        return {
            "success": True,
            "inputs": inputs,
            "count": len(inputs),
            "workflow_analysis": workflow_analysis,
        }
