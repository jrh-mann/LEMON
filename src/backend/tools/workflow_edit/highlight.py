"""Highlight node tool — draws visual attention to a specific node on the canvas.

The orchestrator calls this to pulse/highlight a node when referencing it
in conversation, helping the user see which part of the workflow is being
discussed.
"""

from __future__ import annotations

from typing import Any, Dict

from ..core import Tool, ToolParameter, tool_error


class HighlightNodeTool(Tool):
    name = "highlight_node"
    description = "Highlight a node on the canvas to draw the user's attention to it. The node pulses briefly."
    parameters = [
        ToolParameter("node_id", "string", "ID of the node to highlight"),
    ]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        node_id = args.get("node_id")
        if not node_id:
            return tool_error("node_id is required", "MISSING_NODE_ID")

        return {
            "success": True,
            "action": "highlight_node",
            "node_id": node_id,
            "workflow_id": args.get("workflow_id", ""),
        }
