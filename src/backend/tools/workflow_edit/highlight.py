"""Highlight node tool — draws visual attention to a specific node on the canvas.

The orchestrator calls this to pulse/highlight a node when referencing it
in conversation, helping the user see which part of the workflow is being
discussed.
"""

from __future__ import annotations

from typing import Any, Dict

from ..core import Tool, ToolParameter


class HighlightNodeTool(Tool):
    name = "highlight_node"
    description = (
        "Highlight a node on the canvas so the user can see which one you're "
        "referring to. The node pulses briefly. Use this when answering "
        "questions about specific nodes, when asking the user about a "
        "particular node via `ask_question`, or when pointing out an issue "
        "found by `validate_workflow`."
    )
    parameters = [
        ToolParameter("node_id", "string", "ID of the node to highlight"),
    ]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        node_id = args.get("node_id")
        if not node_id:
            return {"success": False, "error": "node_id is required"}

        return {
            "success": True,
            "action": "highlight_node",
            "node_id": node_id,
            "workflow_id": args.get("workflow_id", ""),
        }
