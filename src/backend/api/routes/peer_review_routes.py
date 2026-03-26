"""Peer review routes for published workflow packages."""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI, Request
from starlette.responses import JSONResponse

from ..deps import require_auth
from ...storage.auth import AuthUser
from ...storage.packages import PackageStore, PublicPackageSummary
from ...storage.workflows import PUBLISH_VOTE_THRESHOLD, WorkflowStore


def _serialize_public_package(
    package, workflow_store: WorkflowStore, package_store: PackageStore, user_id: str
):
    workflows = []
    head = None
    for member in package.members:
        workflow = workflow_store.get_workflow(member.workflow_id, package.user_id)
        if workflow is None:
            continue
        entry = {
            "id": workflow.id,
            "name": workflow.name,
            "description": workflow.description,
            "domain": workflow.domain,
            "tags": workflow.tags,
            "is_validated": workflow.is_validated,
            "role": member.role,
        }
        workflows.append(entry)
        if member.role == "head":
            head = entry
    safe_name = (
        head["name"]
        if head and isinstance(head.get("name"), str)
        else package.name or "Empty package"
    )
    safe_description = (
        head["description"]
        if head and isinstance(head.get("description"), str)
        else package.description or ""
    )
    safe_tags = head["tags"] if head and isinstance(head.get("tags"), list) else []
    safe_domain = head["domain"] if head else None
    return {
        "id": package.id,
        "name": safe_name,
        "description": safe_description,
        "tags": safe_tags,
        "domain": safe_domain,
        "confidence": "none",
        "is_validated": all(w["is_validated"] for w in workflows)
        if workflows
        else False,
        "input_names": [],
        "output_values": [],
        "created_at": package.created_at,
        "updated_at": package.updated_at,
        "is_published": package.is_published,
        "review_status": package.review_status,
        "net_votes": package.net_votes,
        "published_at": package.published_at,
        "publisher_id": package.user_id,
        "user_vote": package_store.get_user_vote(package.id, user_id),
        "workflow_count": len(workflows),
        "head_workflow_id": package.head_workflow_id,
    }


def _serialize_public_package_summary(summary: PublicPackageSummary):
    return {
        "id": summary.id,
        "name": summary.name,
        "description": summary.description,
        "tags": summary.tags,
        "domain": summary.domain,
        "confidence": "none",
        "is_validated": summary.is_validated,
        "input_names": [],
        "output_values": [],
        "created_at": summary.created_at,
        "updated_at": summary.updated_at,
        "is_published": summary.is_published,
        "review_status": summary.review_status,
        "net_votes": summary.net_votes,
        "published_at": summary.published_at,
        "publisher_id": summary.user_id,
        "user_vote": summary.user_vote,
        "workflow_count": summary.workflow_count,
        "head_workflow_id": summary.head_workflow_id,
    }


def register_peer_review_routes(
    app: FastAPI,
    *,
    workflow_store: WorkflowStore,
) -> None:
    router = APIRouter()
    package_store = PackageStore(workflow_store.db_path)

    @router.get("/api/workflows/public")
    async def list_public_workflows(
        request: Request,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        review_status = request.query_params.get("review_status")
        try:
            limit = min(int(request.query_params.get("limit", 100)), 500)
        except (ValueError, TypeError):
            limit = 100
        try:
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except (ValueError, TypeError):
            offset = 0
        if review_status and review_status not in ("unreviewed", "reviewed"):
            return JSONResponse(
                {"error": "review_status must be 'unreviewed' or 'reviewed'"},
                status_code=400,
            )

        packages, total_count = package_store.list_public_package_summaries(
            viewer_user_id=user.id,
            review_status=review_status,
            limit=limit,
            offset=offset,
        )
        return JSONResponse(
            {
                "workflows": [
                    _serialize_public_package_summary(pkg) for pkg in packages
                ],
                "count": total_count,
                "publish_threshold": PUBLISH_VOTE_THRESHOLD,
            }
        )

    @router.get("/api/workflows/public/{package_id}")
    async def get_public_workflow(
        package_id: str,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        package = None
        for candidate in package_store.list_packages(user.id):
            if candidate.id == package_id:
                package = candidate
                break
        if package is None:
            with package_store._conn() as conn:
                row = conn.execute(
                    "SELECT user_id FROM workflow_packages WHERE id = ? AND is_published = 1",
                    (package_id,),
                ).fetchone()
            if row:
                package = package_store.get_package(package_id, row["user_id"])
        if package is None or not package.is_published:
            return JSONResponse(
                {"error": "Published package not found"}, status_code=404
            )

        head_workflow = (
            workflow_store.get_workflow(package.head_workflow_id, package.user_id)
            if package.head_workflow_id
            else None
        )
        return JSONResponse(
            {
                "id": package.id,
                "output_type": head_workflow.output_type if head_workflow else "string",
                "metadata": {
                    "name": head_workflow.name if head_workflow else package.name,
                    "description": head_workflow.description
                    if head_workflow
                    else package.description,
                    "domain": head_workflow.domain if head_workflow else None,
                    "tags": head_workflow.tags if head_workflow else [],
                    "publisher_id": package.user_id,
                    "created_at": package.created_at,
                    "updated_at": package.updated_at,
                    "confidence": "none",
                    "is_validated": bool(head_workflow and head_workflow.is_validated),
                },
                "nodes": head_workflow.nodes if head_workflow else [],
                "edges": head_workflow.edges if head_workflow else [],
                "variables": head_workflow.inputs if head_workflow else [],
                "outputs": head_workflow.outputs if head_workflow else [],
                "tree": head_workflow.tree if head_workflow else {},
                "review_status": package.review_status,
                "net_votes": package.net_votes,
                "published_at": package.published_at,
                "user_vote": package_store.get_user_vote(package.id, user.id),
                "package_id": package.id,
            }
        )

    @router.post("/api/workflows/public/{package_id}/vote")
    async def vote_on_workflow(
        package_id: str,
        request: Request,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        vote = payload.get("vote")
        if vote is None:
            return JSONResponse(
                {"error": "vote is required (+1, -1, or 0 to remove)"}, status_code=400
            )
        vote = int(vote)
        if vote == 0:
            result = package_store.remove_vote(package_id, user.id)
        elif vote in (-1, 1):
            result = package_store.cast_vote(package_id, user.id, vote)
        else:
            return JSONResponse({"error": "vote must be +1, -1, or 0"}, status_code=400)
        return JSONResponse(result)

    app.include_router(router)
