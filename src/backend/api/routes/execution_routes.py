"""Execution routes: run a saved workflow with input values.

Handles the /api/execute/<workflow_id> endpoint which loads a
workflow from storage, runs it through the TreeInterpreter, and
returns the execution result including subflow outputs.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask, jsonify, request, g

from ...storage.workflows import WorkflowStore

logger = logging.getLogger("backend.api")


def register_execution_routes(
    app: Flask,
    *,
    workflow_store: WorkflowStore,
) -> None:
    """Register execution endpoints on the Flask app.

    Args:
        app: Flask application instance.
        workflow_store: Workflow storage backend for loading workflows.
    """

    @app.post("/api/execute/<workflow_id>")
    def execute_workflow(workflow_id: str) -> Any:
        """Execute a workflow with provided input values.

        Request body should contain input values keyed by input name:
        {
            "Age": 25,
            "Income": 50000.0,
            "Smoker": false
        }

        Supports subprocess nodes that reference other workflows.
        Subflow outputs are injected as new inputs for subsequent decisions.
        """
        from ...execution.interpreter import TreeInterpreter

        user_id = g.auth_user.id

        # Load the workflow
        workflow = workflow_store.get_workflow(workflow_id, user_id)
        if not workflow:
            return jsonify({
                "success": False,
                "error": f"Workflow '{workflow_id}' not found",
                "path": [],
                "context": {},
            }), 404

        # Validate workflow has tree structure
        if not workflow.tree or "start" not in workflow.tree:
            return jsonify({
                "success": False,
                "error": (
                    "Workflow has no execution tree. "
                    "Build the workflow tree first."
                ),
                "path": [],
                "context": {},
            }), 400

        # Get input values from request
        payload = request.get_json(force=True, silent=True) or {}

        # Convert input names to input IDs for the interpreter
        # User provides: {"Age": 25} -> interpreter needs: {"input_age_int": 25}
        input_values = {}
        for inp in workflow.inputs:
            inp_name = inp.get("name")
            inp_id = inp.get("id")

            if inp_name in payload:
                input_values[inp_id] = payload[inp_name]
            elif inp_id in payload:
                # Also accept input IDs directly
                input_values[inp_id] = payload[inp_id]

        # Create interpreter with workflow_store for subflow support
        interpreter = TreeInterpreter(
            tree=workflow.tree,
            variables=workflow.inputs,  # Storage field is 'inputs', maps to variables param
            outputs=workflow.outputs,
            workflow_id=workflow_id,
            call_stack=[],
            workflow_store=workflow_store,
            user_id=user_id,
            output_type=workflow.output_type or "string",
        )

        # Execute workflow
        result = interpreter.execute(input_values)

        # Build response
        response = {
            "success": result.success,
            "output": result.output,
            "path": result.path,
            "context": result.context,
            "error": result.error,
        }

        # Include subflow execution details if any
        if result.subflow_results:
            response["subflow_results"] = result.subflow_results

        return jsonify(response)
