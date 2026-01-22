"""Remove workflow input tool."""

from __future__ import annotations

from typing import Any, Dict

from ..core import Tool, ToolParameter
from .helpers import ensure_workflow_analysis, normalize_input_name


class RemoveWorkflowInputTool(Tool):
    """Remove a registered workflow input."""

    name = "remove_workflow_input"
    description = (
        "Remove a registered workflow input by name (case-insensitive). "
        "If the input is referenced by nodes, deletion will fail by default. "
        "Use force=true to cascade delete (automatically removes input_ref from all nodes)."
    )
    parameters = [
        ToolParameter(
            "name",
            "string",
            "Name of the input to remove (case-insensitive)",
            required=True,
        ),
        ToolParameter(
            "force",
            "boolean",
            "If true, removes input even if referenced by nodes (cascade delete). Default: false",
            required=False,
        ),
    ]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        workflow_analysis = ensure_workflow_analysis(session_state)
        current_workflow = session_state.get("current_workflow", {"nodes": [], "edges": []})
        inputs = workflow_analysis.get("inputs", [])

        name = args.get("name")

        # Explicitly convert force to boolean (handles string "true"/"false" from MCP)
        force_raw = args.get("force", False)
        if isinstance(force_raw, str):
            force = force_raw.lower() in ("true", "1", "yes")
        else:
            force = bool(force_raw)

        if not name or not isinstance(name, str):
            return {"success": False, "error": "Input 'name' is required"}

        normalized_name = normalize_input_name(name)

        # Check if input exists
        if not any(normalize_input_name(inp.get("name", "")) == normalized_name for inp in inputs):
            return {
                "success": False,
                "error": f"Input '{name}' not found"
            }

        # Check for nodes that reference this input
        referencing_nodes = [
            node for node in current_workflow.get("nodes", [])
            if normalize_input_name(node.get("input_ref", "")) == normalized_name
        ]

        # If references exist and force is not enabled, reject deletion
        if referencing_nodes and not force:
            node_labels = [
                node.get("label", node.get("id", "unknown"))
                for node in referencing_nodes[:3]  # Show first 3
            ]
            more_count = len(referencing_nodes) - 3

            error_msg = (
                f"Cannot remove input '{name}': it is referenced by {len(referencing_nodes)} node(s): "
                f"{', '.join(node_labels)}"
            )
            if more_count > 0:
                error_msg += f", and {more_count} more"
            error_msg += ". Either remove the references manually, or use force=true to cascade delete."

            return {
                "success": False,
                "error": error_msg,
                "referencing_nodes": [node.get("id") for node in referencing_nodes],
            }

        # If force=true, remove input_ref from all referencing nodes
        affected_node_labels = []
        if referencing_nodes:
            for node in referencing_nodes:
                if "input_ref" in node:
                    del node["input_ref"]
                    affected_node_labels.append(node.get("label", node.get("id", "unknown")))

        # Remove the input from the inputs list
        workflow_analysis["inputs"] = [
            inp for inp in inputs
            if normalize_input_name(inp.get("name", "")) != normalized_name
        ]

        # Build success message
        message = f"Removed input '{name}'"
        if affected_node_labels:
            message += f" and cleared references from {len(affected_node_labels)} node(s): {', '.join(affected_node_labels[:3])}"
            if len(affected_node_labels) > 3:
                message += f", and {len(affected_node_labels) - 3} more"

        return {
            "success": True,
            "message": message,
            "workflow_analysis": workflow_analysis,
            "current_workflow": current_workflow,  # Return updated workflow
            "affected_nodes": len(affected_node_labels),
        }
