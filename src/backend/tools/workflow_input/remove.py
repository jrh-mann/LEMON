"""Remove workflow variable tool.

Multi-workflow architecture:
- Requires workflow_id parameter (workflow must exist in library)
- Loads workflow from database at start
- Auto-saves changes back to database when done
"""

from __future__ import annotations

from typing import Any, Dict

from ..core import Tool, ToolParameter
from ..workflow_edit.helpers import load_workflow_for_tool, save_workflow_changes
from .helpers import normalize_variable_name


class RemoveWorkflowVariableTool(Tool):
    """Remove a registered workflow input variable.
    
    Only removes variables with source='input'. Subprocess/calculated variables
    should be removed by modifying or deleting the nodes that create them.
    
    Requires workflow_id - the workflow must exist in the library first.
    """

    name = "remove_workflow_variable"
    aliases = ["remove_workflow_input"]  # Backwards compatibility
    description = (
        "Remove a registered workflow input variable by name (case-insensitive). "
        "Requires workflow_id. "
        "If the variable is used in decision node conditions, deletion will fail by default. "
        "Use force=true to cascade delete (automatically clears condition from affected nodes)."
    )
    parameters = [
        # workflow_id is REQUIRED and must be first
        ToolParameter(
            "workflow_id",
            "string",
            "ID of the workflow containing the variable (from create_workflow)",
            required=True,
        ),
        ToolParameter(
            "name",
            "string",
            "Name of the input variable to remove (case-insensitive)",
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
        workflow_id = args.get("workflow_id")

        # Load workflow from database
        workflow_data, error = load_workflow_for_tool(workflow_id, session_state)
        if error:
            return error

        # Extract data from loaded workflow
        nodes = list(workflow_data["nodes"])
        variables = list(workflow_data["variables"])
        
        # Filter for input variables only
        input_variables = [v for v in variables if v.get("source") == "input"]

        name = args.get("name")

        # Explicitly convert force to boolean (handles string "true"/"false" from MCP)
        force_raw = args.get("force", False)
        if isinstance(force_raw, str):
            force = force_raw.lower() in ("true", "1", "yes")
        else:
            force = bool(force_raw)

        if not name or not isinstance(name, str):
            return {"success": False, "error": "Variable 'name' is required"}

        normalized_name = normalize_variable_name(name)

        # Check if input variable exists (only check source='input' variables)
        found_var = None
        for var in input_variables:
            if normalize_variable_name(var.get("name", "")) == normalized_name:
                found_var = var
                break
        
        if not found_var:
            return {
                "success": False,
                "error": f"Input variable '{name}' not found"
            }

        # Check for nodes that reference this input in their condition
        referencing_nodes = []
        for node in nodes:
            condition = node.get("condition")
            if condition and condition.get("input_id") == found_var.get("id"):
                referencing_nodes.append(node)

        # If references exist and force is not enabled, reject deletion
        if referencing_nodes and not force:
            node_labels = [
                node.get("label", node.get("id", "unknown"))
                for node in referencing_nodes[:3]  # Show first 3
            ]
            more_count = len(referencing_nodes) - 3

            error_msg = (
                f"Cannot remove variable '{name}': it is referenced by {len(referencing_nodes)} node(s): "
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

        # If force=true, clear condition from all referencing nodes
        nodes_modified = False
        affected_node_labels = []
        if referencing_nodes:
            for node in nodes:
                condition = node.get("condition")
                if condition and condition.get("input_id") == found_var.get("id"):
                    del node["condition"]
                    affected_node_labels.append(node.get("label", node.get("id", "unknown")))
                    nodes_modified = True

        # Remove the variable from the variables list (match by ID for precision)
        variables = [
            var for var in variables
            if var.get("id") != found_var.get("id")
        ]

        # Auto-save changes to database
        save_kwargs: Dict[str, Any] = {"variables": variables}
        if nodes_modified:
            save_kwargs["nodes"] = nodes
        
        save_error = save_workflow_changes(workflow_id, session_state, **save_kwargs)
        if save_error:
            return save_error

        # Build success message
        message = f"Removed variable '{name}' from workflow {workflow_id}"
        if affected_node_labels:
            message += f" and cleared references from {len(affected_node_labels)} node(s): {', '.join(affected_node_labels[:3])}"
            if len(affected_node_labels) > 3:
                message += f", and {len(affected_node_labels) - 3} more"

        return {
            "success": True,
            "workflow_id": workflow_id,
            "message": message,
            "affected_nodes": len(affected_node_labels),
        }
