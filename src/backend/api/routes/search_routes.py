"""Search and domain listing routes.

Handles workflow search with filters (GET /api/search) and
domain enumeration (GET /api/domains).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI, Request
from starlette.responses import JSONResponse

from ..deps import require_auth
from ...storage.auth import AuthUser
from .helpers import serialize_workflow_summary
from ...storage.workflows import WorkflowStore


def register_search_routes(
    app: FastAPI,
    *,
    workflow_store: WorkflowStore,
) -> None:
    """Register search endpoints on the FastAPI app.

    Args:
        app: FastAPI application instance.
        workflow_store: Workflow storage backend.
    """
    router = APIRouter()

    @router.get("/api/search")
    async def search_workflows(
        request: Request,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        """Search workflows with filters.

        All workflows in the database are considered "saved" workflows.
        """
        query = request.query_params.get("q")
        domain = request.query_params.get("domain")
        validated = request.query_params.get("validated")
        limit = min(int(request.query_params.get("limit", 100)), 500)
        offset = max(int(request.query_params.get("offset", 0)), 0)

        # Convert validated string to bool if provided
        validated_bool = None
        if validated is not None:
            validated_bool = validated.lower() in ("true", "1", "yes")

        workflows, total_count = workflow_store.search_workflows(
            user.id,
            query=query,
            domain=domain,
            validated=validated_bool,
            limit=limit,
            offset=offset,
        )

        summaries = [serialize_workflow_summary(wf) for wf in workflows]
        return JSONResponse({"workflows": summaries, "count": total_count})

    @router.get("/api/domains")
    async def list_domains(
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        """Get list of unique domains used in user's workflows."""
        domains = workflow_store.get_domains(user.id)
        return JSONResponse({"domains": domains})

    app.include_router(router)
