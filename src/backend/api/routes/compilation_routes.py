"""Compilation routes: compile workflow to Python code.

Handles the /api/workflows/compile endpoint which converts a
workflow definition (nodes, edges, variables) into standalone
Python source code.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI, Request
from starlette.responses import JSONResponse

from ..deps import require_auth
from ...storage.auth import AuthUser
from ...storage.workflows import WorkflowStore


def register_compilation_routes(
    app: FastAPI,
    *,
    workflow_store: WorkflowStore,
) -> None:
    """Register compilation endpoints on the FastAPI app.

    Args:
        app: FastAPI application instance.
        workflow_store: Workflow storage backend for subflow resolution.
    """
    router = APIRouter()

    @router.post("/api/workflows/compile")
    async def compile_workflow_to_python_endpoint(
        request: Request,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        """Compile a workflow to Python code.

        Request body:
        {
            "nodes": [...],
            "edges": [...],
            "variables": [...],
            "outputs": [...],  # optional
            "name": "Workflow Name",  # optional
            "include_imports": true,  # optional, default true
            "include_docstring": true,  # optional, default true
            "include_main": false  # optional, default false
        }

        Returns:
        {
            "success": true,
            "code": "def workflow_name(...): ...",
            "warnings": []
        }
        """
        from ...execution.python_compiler import compile_workflow_to_python

        try:
            payload = await request.json()
        except Exception:
            payload = {}

        nodes = payload.get("nodes", [])
        edges = payload.get("edges", [])
        variables = payload.get("variables", [])
        outputs = payload.get("outputs")
        workflow_name = payload.get("name", "workflow")

        # Optional generation flags
        include_imports = payload.get("include_imports", True)
        include_docstring = payload.get("include_docstring", True)
        include_main = payload.get("include_main", False)

        # Validate required fields
        if not nodes:
            return JSONResponse(
                {
                    "success": False,
                    "error": "No nodes provided",
                    "code": None,
                    "warnings": [],
                },
                status_code=400,
            )

        # Closure to securely fetch subflows within user's permission domain
        def _fetch_subworkflow(sub_id: str):
            return workflow_store.get_workflow(sub_id, user.id)

        # Compile workflow to Python
        result = compile_workflow_to_python(
            nodes=nodes,
            edges=edges,
            variables=variables,
            outputs=outputs,
            workflow_name=workflow_name,
            include_imports=include_imports,
            include_docstring=include_docstring,
            include_main=include_main,
            fetch_subworkflow=_fetch_subworkflow,
        )

        if result.success:
            return JSONResponse({
                "success": True,
                "code": result.code,
                "warnings": result.warnings,
                "partial_failure": result.partial_failure,
            })
        else:
            return JSONResponse(
                {
                    "success": False,
                    "error": result.error,
                    "code": None,
                    "warnings": result.warnings,
                    "partial_failure": result.partial_failure,
                },
                status_code=400,
            )

    app.include_router(router)
