"""Execute workflow tool — lets the LLM run a workflow by ID."""

from __future__ import annotations

from typing import Any, Dict

from ..execution.interpreter import TreeInterpreter
from ..execution.preparation import prepare_workflow_execution
from .core import WorkflowTool, ToolParameter


class ExecuteWorkflowTool(WorkflowTool):
    """Execute a workflow with provided input values.

    Loads the workflow from the database by ID, builds a tree from its
    nodes/edges, validates it, then runs the TreeInterpreter and returns
    the execution result (output, path taken, final variable context, and
    any errors).
    """

    name = "execute_workflow"
    description = (
        "Run the active workflow with the given input values and return the result. "
        "Provide input values as a JSON object mapping variable names to their values. "
        "Returns the output, the path of nodes visited, and the final variable context. "
        "Use this when the user asks to run, execute, test, or try the workflow."
    )
    parameters = [
        ToolParameter(
            "input_values",
            "object",
            (
                "Input values keyed by variable name or ID. "
                "Example: {\"Age\": 25, \"Smoker\": false}"
            ),
            required=True,
        ),
    ]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        workflow_data, error = self._load_workflow(args, **kwargs)
        if error:
            return error
        workflow_id = workflow_data["workflow_id"]
        session_state = kwargs.get("session_state", {})

        nodes = workflow_data["nodes"]
        edges = workflow_data["edges"]
        variables = workflow_data["variables"]
        outputs = workflow_data.get("outputs", [])

        if not nodes:
            return {
                "success": False,
                "error": "Workflow has no nodes. Build the workflow first.",
            }

        tree, preparation_error, validation_errors = prepare_workflow_execution(
            nodes=nodes,
            edges=edges,
            variables=variables,
        )
        if preparation_error:
            return {
                "success": False,
                "error": (
                    "Workflow validation failed — fix these before executing:\n"
                    + preparation_error
                ),
                "validation_errors": [
                    {"code": e.code, "message": e.message, "node_id": e.node_id}
                    for e in validation_errors or []
                ],
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
            output_type=workflow_data.get("output_type", "string"),
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
