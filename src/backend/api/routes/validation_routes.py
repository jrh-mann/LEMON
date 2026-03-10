"""Validation routes: validate workflow structure.

Provides the /api/validate endpoint for pre-save structural checks.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI, Request
from starlette.responses import JSONResponse

from ..deps import require_auth
from ...storage.auth import AuthUser


def register_validation_routes(app: FastAPI) -> None:
    """Register validation endpoints on the FastAPI app.

    Args:
        app: FastAPI application instance.
    """
    router = APIRouter()

    @router.post("/api/validate")
    async def validate_workflow_endpoint(
        request: Request,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        """Validate a workflow structure before saving/exporting."""
        from ...validation.workflow_validator import WorkflowValidator

        try:
            payload = await request.json()
        except Exception:
            payload = {}

        nodes = payload.get("nodes", [])
        edges = payload.get("edges", [])
        variables = payload.get("variables", [])

        validator = WorkflowValidator()
        workflow_to_validate = {
            "nodes": nodes,
            "edges": edges,
            "variables": variables,
        }

        # Use strict=True to check for unreachable nodes and complete structure
        is_valid, errors = validator.validate(workflow_to_validate, strict=True)

        if is_valid:
            return JSONResponse({
                "success": True,
                "valid": True,
                "message": (
                    "Workflow is valid. All nodes are reachable "
                    "and connected correctly."
                ),
            })
        else:
            error_message = validator.format_errors(errors)
            return JSONResponse({
                "success": True,
                "valid": False,
                "errors": [
                    {
                        "code": e.code,
                        "message": e.message,
                        "node_id": e.node_id,
                    }
                    for e in errors
                ],
                "message": error_message,
            })

    app.include_router(router)
