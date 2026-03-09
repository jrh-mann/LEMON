"""Execution routes: run a saved workflow with input values.

Handles the /api/execute/<workflow_id> endpoint which loads a
workflow from storage, runs it through the TreeInterpreter, and
returns the execution result including subflow outputs.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, FastAPI, Request
from starlette.responses import JSONResponse

from ..deps import require_auth
from ...storage.auth import AuthUser
from ...execution.preparation import prepare_record_execution
from ...storage.workflows import WorkflowStore

logger = logging.getLogger("backend.api")


def register_execution_routes(
    app: FastAPI,
    *,
    workflow_store: WorkflowStore,
) -> None:
    """Register execution endpoints on the FastAPI app.

    Args:
        app: FastAPI application instance.
        workflow_store: Workflow storage backend for loading workflows.
    """
    router = APIRouter()

    @router.post("/api/execute/{workflow_id}")
    async def execute_workflow(
        workflow_id: str,
        request: Request,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
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

        # Load the workflow
        workflow = workflow_store.get_workflow(workflow_id, user.id)
        if not workflow:
            return JSONResponse(
                {
                    "success": False,
                    "error": f"Workflow '{workflow_id}' not found",
                    "path": [],
                    "context": {},
                },
                status_code=404,
            )

        tree, preparation_error, validation_errors = prepare_record_execution(workflow)
        if preparation_error:
            response = {
                "success": False,
                "error": preparation_error,
                "path": [],
                "context": {},
            }
            if validation_errors:
                response["validation_errors"] = [
                    {"code": e.code, "message": e.message, "node_id": e.node_id}
                    for e in validation_errors
                ]
            return JSONResponse(response, status_code=400)

        # Get input values from request
        try:
            payload = await request.json()
        except Exception:
            payload = {}

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
            tree=tree,
            variables=workflow.inputs,  # Storage field is 'inputs', maps to variables param
            outputs=workflow.outputs,
            workflow_id=workflow_id,
            call_stack=[],
            workflow_store=workflow_store,
            user_id=user.id,
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

        return JSONResponse(response)

    app.include_router(router)
