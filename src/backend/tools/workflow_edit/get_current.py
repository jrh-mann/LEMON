"""Get current workflow tool."""

from __future__ import annotations

from typing import Any, Dict, List

from ..core import Tool, ToolParameter


class GetCurrentWorkflowTool(Tool):
    """Get the current workflow displayed on the canvas."""

    name = "get_current_workflow"
    description = "Get the current workflow displayed on the canvas as JSON (nodes and edges)."
    parameters: List[ToolParameter] = []

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        workflow = session_state.get("current_workflow", {"nodes": [], "edges": []})

        node_descriptions = []
        for node in workflow.get("nodes", []):
            desc = f"- {node['id']}: \"{node['label']}\" (type: {node['type']})"
            node_descriptions.append(desc)

        edge_descriptions = []
        for edge in workflow.get("edges", []):
            from_label = next(
                (n["label"] for n in workflow.get("nodes", []) if n["id"] == edge["from"]),
                "?",
            )
            to_label = next(
                (n["label"] for n in workflow.get("nodes", []) if n["id"] == edge["to"]),
                "?",
            )
            label_part = f" [{edge.get('label', '')}]" if edge.get("label") else ""
            desc = f"- {edge['from']} -> {edge['to']}: \"{from_label}\"{label_part} -> \"{to_label}\""
            edge_descriptions.append(desc)

        return {
            "success": True,
            "workflow": workflow,
            "node_count": len(workflow.get("nodes", [])),
            "edge_count": len(workflow.get("edges", [])),
            "summary": {
                "node_count": len(workflow.get("nodes", [])),
                "edge_count": len(workflow.get("edges", [])),
                "node_descriptions": (
                    "\n".join(node_descriptions) if node_descriptions else "No nodes"
                ),
                "edge_descriptions": (
                    "\n".join(edge_descriptions) if edge_descriptions else "No connections"
                ),
            },
        }
