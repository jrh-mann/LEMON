from __future__ import annotations

import json
from typing import Any, Dict

from fastapi import APIRouter, Depends, FastAPI, Request
from starlette.responses import JSONResponse

from ..deps import require_auth
from ...storage.auth import AuthUser
from ...storage.workflows import WorkflowStore
from ...workflow_package_service import WorkflowPackageService


def _serialize_package(
    package, workflow_store: WorkflowStore, user_id: str
) -> Dict[str, Any]:
    workflows = []
    for member in package.members:
        workflow = workflow_store.get_workflow(member.workflow_id, user_id)
        if workflow is None:
            continue
        workflows.append(
            {
                "id": workflow.id,
                "name": workflow.name,
                "description": workflow.description,
                "domain": workflow.domain,
                "tags": workflow.tags,
                "is_validated": workflow.is_validated,
                "is_draft": workflow.is_draft,
                "role": member.role,
            }
        )
    head_workflow = next(
        (workflow for workflow in workflows if workflow["role"] == "head"), None
    )
    return {
        "id": package.id,
        "name": head_workflow["name"] if head_workflow else package.name,
        "description": head_workflow["description"]
        if head_workflow
        else package.description,
        "head_workflow_id": package.head_workflow_id,
        "is_published": package.is_published,
        "review_status": package.review_status,
        "net_votes": package.net_votes,
        "published_at": package.published_at,
        "workflow_count": len(workflows),
        "workflows": workflows,
    }


def register_package_routes(app: FastAPI, *, workflow_store: WorkflowStore) -> None:
    router = APIRouter()
    service = WorkflowPackageService(workflow_store)

    @router.get("/api/packages")
    async def list_packages(user: AuthUser = Depends(require_auth)) -> JSONResponse:
        packages = service.list_packages(user.id)
        return JSONResponse(
            {
                "packages": [
                    _serialize_package(pkg, workflow_store, user.id) for pkg in packages
                ]
            }
        )

    @router.post("/api/packages")
    async def create_package(
        request: Request, user: AuthUser = Depends(require_auth)
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError):
            payload = {}
        package = service.create_package(
            user.id,
            name=str(payload.get("name") or ""),
            description=str(payload.get("description") or ""),
        )
        return JSONResponse(
            _serialize_package(package, workflow_store, user.id), status_code=201
        )

    @router.get("/api/packages/{package_id}")
    async def get_package(
        package_id: str, user: AuthUser = Depends(require_auth)
    ) -> JSONResponse:
        package = service.get_package(user.id, package_id)
        if package is None:
            return JSONResponse({"error": "Package not found"}, status_code=404)
        issues = [
            issue.__dict__ for issue in service.validate_package(user.id, package_id)
        ]
        body = _serialize_package(package, workflow_store, user.id)
        body["issues"] = issues
        body["is_publishable"] = not issues
        return JSONResponse(body)

    @router.patch("/api/packages/{package_id}")
    async def update_package(
        package_id: str, request: Request, user: AuthUser = Depends(require_auth)
    ) -> JSONResponse:
        payload = await request.json()
        success = service.package_store.update_package(
            package_id,
            user.id,
            name=payload.get("name"),
            description=payload.get("description"),
        )
        if not success:
            return JSONResponse({"error": "Package not found"}, status_code=404)
        package = service.get_package(user.id, package_id)
        return JSONResponse(_serialize_package(package, workflow_store, user.id))

    @router.delete("/api/packages/{package_id}")
    async def delete_package(
        package_id: str, user: AuthUser = Depends(require_auth)
    ) -> JSONResponse:
        success = service.package_store.delete_package(package_id, user.id)
        if not success:
            return JSONResponse({"error": "Package not found"}, status_code=404)
        return JSONResponse({"success": True})

    @router.post("/api/packages/{package_id}/members")
    async def add_package_member(
        package_id: str, request: Request, user: AuthUser = Depends(require_auth)
    ) -> JSONResponse:
        payload = await request.json()
        workflow_id = payload.get("workflow_id")
        package = service.add_workflow(user.id, package_id, workflow_id)
        return JSONResponse(_serialize_package(package, workflow_store, user.id))

    @router.delete("/api/packages/{package_id}/members/{workflow_id}")
    async def delete_package_member(
        package_id: str, workflow_id: str, user: AuthUser = Depends(require_auth)
    ) -> JSONResponse:
        package = service.remove_workflow(user.id, package_id, workflow_id)
        return JSONResponse(_serialize_package(package, workflow_store, user.id))

    @router.post("/api/packages/{package_id}/head")
    async def set_package_head(
        package_id: str, request: Request, user: AuthUser = Depends(require_auth)
    ) -> JSONResponse:
        payload = await request.json()
        package = service.set_head_workflow(
            user.id, package_id, payload.get("workflow_id")
        )
        return JSONResponse(_serialize_package(package, workflow_store, user.id))

    @router.post("/api/packages/{package_id}/publish")
    async def publish_package(
        package_id: str, user: AuthUser = Depends(require_auth)
    ) -> JSONResponse:
        try:
            package = service.publish_package(user.id, package_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(_serialize_package(package, workflow_store, user.id))

    @router.post("/api/packages/{package_id}/autofetch-subflows/preview")
    async def preview_autofetch_subflows(
        package_id: str, user: AuthUser = Depends(require_auth)
    ) -> JSONResponse:
        try:
            preview = service.autofetch_subflows_preview(user.id, package_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(preview)

    @router.post("/api/packages/{package_id}/autofetch-subflows/apply")
    async def apply_autofetch_subflows(
        package_id: str, request: Request, user: AuthUser = Depends(require_auth)
    ) -> JSONResponse:
        payload = await request.json()
        clone_ids = payload.get("clone_conflict_workflow_ids") or []
        try:
            package, details = service.autofetch_subflows_apply(
                user.id,
                package_id,
                clone_conflict_workflow_ids=clone_ids,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        body = _serialize_package(package, workflow_store, user.id)
        body["autofetch"] = details
        return JSONResponse(body)

    app.include_router(router)
