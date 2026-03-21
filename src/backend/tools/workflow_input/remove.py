"""Remove workflow variable tool.

Multi-workflow architecture:
- Uses current_workflow_id from session_state (implicit binding)
- Loads workflow from database at start
- Auto-saves changes back to database when done
"""

from __future__ import annotations

from typing import Any, Dict

from ..core import WorkflowTool, ToolParameter
from ..workflow_edit.helpers import save_workflow_changes
from .helpers import normalize_variable_name
from .reference_updates import find_variable_references


class RemoveWorkflowVariableTool(WorkflowTool):
    """Remove a registered workflow input variable.
    
    Only removes variables with source='input'. Subprocess/calculated variables
    should be removed by modifying or deleting the nodes that create them.
    
    Uses the current workflow from session state.
    """

    uses_validator = False

    name = "remove_workflow_variable"
    description = (
        "Remove a registered input variable from the active workflow by name (case-insensitive). "
        "If the variable is used in decision node conditions, deletion will fail by default. "
        "Use force=true to cascade delete (automatically clears conditions from affected nodes)."
    )
    parameters = [
        ToolParameter(
            "name",
            "string",
            "Name of the variable to remove (case-insensitive)",
            required=True,
        ),
        ToolParameter(
            "force",
            "boolean",
            "If true, removes variable even if referenced by nodes (cascade delete). Default: false",
            required=False,
        ),
    ]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        workflow_data, error = self._load_workflow(args, **kwargs)
        if error:
            return error
        workflow_id = workflow_data["workflow_id"]
        session_state = kwargs.get("session_state", {})

        # Extract data from loaded workflow
        nodes = list(workflow_data["nodes"])
        variables = list(workflow_data["variables"])
        
        # Filter for input variables only
        input_variables = [v for v in variables if v.get("source") == "input"]

        name = args.get("name")

        # Explicitly convert force to boolean (handles string "true"/"false" from JSON)
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

        var_id = found_var.get("id")
        referencing_nodes = find_variable_references(nodes, str(var_id))

        # If references exist and force is not enabled, reject deletion
        if referencing_nodes and not force:
            node_labels = [
                ref["node_label"]
                for ref in referencing_nodes[:3]
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
                "referencing_nodes": [ref["node_id"] for ref in referencing_nodes],
            }

        # If force=true, clear all references (condition, calculation, output_variable)
        # from nodes that use this variable.
        # For compound conditions referencing the variable in any sub-condition,
        # we clear the entire condition (partial removal would break the compound).
        nodes_modified = False
        affected_node_labels = []
        if referencing_nodes:
            for node in nodes:
                node_touched = False

                # Clear condition references
                condition = node.get("condition")
                if condition:
                    should_clear = False
                    if "operator" in condition:
                        for sub in condition.get("conditions", []):
                            if isinstance(sub, dict) and sub.get("input_id") == var_id:
                                should_clear = True
                                break
                    elif condition.get("input_id") == var_id:
                        should_clear = True
                    if should_clear:
                        del node["condition"]
                        node_touched = True

                # Clear calculation operand references
                calculation = node.get("calculation")
                if isinstance(calculation, dict):
                    operands = calculation.get("operands", [])
                    new_operands = [
                        op for op in operands
                        if not (isinstance(op, dict) and op.get("kind") == "variable" and op.get("ref") == var_id)
                    ]
                    if len(new_operands) != len(operands):
                        calculation["operands"] = new_operands
                        node_touched = True

                # Clear output_variable references
                if node.get("output_variable") == var_id:
                    del node["output_variable"]
                    node_touched = True

                if node_touched:
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

        result: Dict[str, Any] = {
            "success": True,
            "workflow_id": workflow_id,
            "message": message,
            "affected_nodes": len(affected_node_labels),
            # Return workflow_analysis for orchestrator to sync local state
            "workflow_analysis": {"variables": variables},
        }
        
        # If nodes were modified (force delete), also return current_workflow
        if nodes_modified:
            result["current_workflow"] = {"nodes": nodes}
        
        return result
