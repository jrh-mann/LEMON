"""Execute workflow tool — lets the LLM run a workflow by ID."""

from __future__ import annotations

from typing import Any, Dict

from ..execution.interpreter import TreeInterpreter
from ..utils.flowchart import tree_from_flowchart
from ..validation.workflow_validator import WorkflowValidator
from .core import Tool, ToolParameter
from .workflow_edit.helpers import load_workflow_for_tool


class ExecuteWorkflowTool(Tool):
    """Execute a workflow with provided input values.

    Loads the workflow from the database by ID, builds a tree from its
    nodes/edges, validates it, then runs the TreeInterpreter and returns
    the execution result (output, path taken, final variable context, and
    any errors).
    """

    name = "execute_workflow"
    description = (
        "Run a workflow with the given input values and return the result. "
        "Provide the workflow_id and input values as a JSON object mapping "
        "variable names (or IDs) to their values. Returns the output, the "
        "path of nodes visited, and the final variable context."
    )
    parameters = [
        ToolParameter(
            "workflow_id",
            "string",
            "ID of the workflow to execute",
            required=True,
        ),
        ToolParameter(
            "input_values",
            "object",
            (
                "Input values for the workflow, keyed by variable name or ID. "
                "Example: {\"Age\": 25, \"Smoker\": false}"
            ),
            required=True,
        ),
    ]

    def __init__(self) -> None:
        self.validator = WorkflowValidator()

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        workflow_id = args.get("workflow_id")

        if not workflow_id:
            return {
                "success": False,
                "error": "workflow_id is required",
            }

        # Load workflow from database
        workflow_data, error = load_workflow_for_tool(workflow_id, session_state)
        if error:
            return error
        # Use the workflow_id from loaded data (handles fallback to current_workflow_id)
        workflow_id = workflow_data["workflow_id"]

        nodes = workflow_data["nodes"]
        edges = workflow_data["edges"]
        variables = workflow_data["variables"]
        outputs = workflow_data.get("outputs", [])

        if not nodes:
            return {
                "success": False,
                "error": "Workflow has no nodes. Build the workflow first.",
            }

        # Validate before executing
        workflow_for_validation = {
            "nodes": nodes,
            "edges": edges,
            "variables": variables,
        }
        is_valid, errors = self.validator.validate(
            workflow_for_validation, strict=True,
        )
        if not is_valid:
            return {
                "success": False,
                "error": (
                    "Workflow validation failed — fix these before executing:\n"
                    + self.validator.format_errors(errors)
                ),
            }

        # Build execution tree from nodes/edges
        tree = tree_from_flowchart(nodes, edges)
        if not tree or "start" not in tree:
            return {
                "success": False,
                "error": "Workflow has no start node.",
            }

        # Resolve input values: accept variable names or IDs
        raw_inputs = args.get("input_values", {})
        name_to_id = {v["name"]: v["id"] for v in variables if "name" in v and "id" in v}
        resolved_inputs: Dict[str, Any] = {}
        for key, value in raw_inputs.items():
            if key in name_to_id:
                resolved_inputs[name_to_id[key]] = value
            else:
                # Assume it's already an ID
                resolved_inputs[key] = value

        # Execute
        workflow_store = session_state.get("workflow_store")
        user_id = session_state.get("user_id")

        interpreter = TreeInterpreter(
            tree=tree,
            variables=variables,
            outputs=outputs,
            workflow_store=workflow_store,
            user_id=user_id,
        )

        try:
            result = interpreter.execute(resolved_inputs)
        except Exception as exc:
            return {
                "success": False,
                "error": f"Execution failed: {exc}",
            }

        response: Dict[str, Any] = {
            "success": result.success,
            "workflow_id": workflow_id,
            "output": result.output,
            "path": result.path,
            "context": result.context,
            "error": result.error,
        }
        if result.subflow_results:
            response["subflow_results"] = result.subflow_results
        return response
