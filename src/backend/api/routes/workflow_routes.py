"""Workflow CRUD routes: list, create, get, delete, patch, update.

Handles all user-owned workflow operations including creation,
retrieval, modification, and deletion. Validates workflow structure
before saving.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Request
from starlette.responses import FileResponse, JSONResponse

from ..deps import require_auth
from ...storage.auth import AuthUser
from .helpers import _calculate_confidence, _infer_outputs_from_nodes
from ...storage.workflows import WorkflowStore
from ...utils.flowchart import tree_from_flowchart
from ...utils.paths import lemon_data_dir
from ...validation.workflow_validator import WorkflowValidator

logger = logging.getLogger("backend.api")

# Workflow validator instance for save/update validation
_workflow_validator = WorkflowValidator()


def _serialize_workflow_summary(wf: Any) -> Dict[str, Any]:
    """Convert a WorkflowRecord to WorkflowSummary format for list endpoints."""
    from .helpers import serialize_workflow_summary

    return serialize_workflow_summary(wf)


def register_workflow_routes(
    app: FastAPI,
    *,
    workflow_store: WorkflowStore,
    repo_root: Optional[Path] = None,
) -> None:
    """Register workflow CRUD endpoints on the FastAPI app.

    Args:
        app: FastAPI application instance.
        workflow_store: Workflow storage backend.
        repo_root: Repository root for resolving upload paths.
    """
    router = APIRouter()

    @router.get("/api/workflows")
    async def list_workflows(
        request: Request,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        """List all workflows for the authenticated user.

        All workflows in the database are considered "saved" workflows.
        The current canvas workflow (if unsaved) is not included - use the
        LLM's list_workflows_in_library tool to see that.
        """
        try:
            limit = min(int(request.query_params.get("limit", 100)), 500)
        except (ValueError, TypeError):
            limit = 100
        try:
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except (ValueError, TypeError):
            offset = 0

        workflows, total_count = workflow_store.list_workflows(
            user.id,
            limit=limit,
            offset=offset,
        )

        summaries = [_serialize_workflow_summary(wf) for wf in workflows]
        return JSONResponse({"workflows": summaries, "count": total_count})

    @router.post("/api/workflows")
    async def create_workflow(
        request: Request,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        """Save a new workflow for the authenticated user."""
        try:
            payload = await request.json()
        except Exception:
            payload = {}

        # Extract workflow data from payload
        workflow_id = payload.get("id") or f"wf_{uuid4().hex}"
        name = payload.get("name") or "Untitled Workflow"
        description = payload.get("description") or ""
        domain = payload.get("domain")
        tags = payload.get("tags") or []
        output_type = payload.get("output_type", "string")

        # Extract workflow structure (nodes, edges, variables, doubts)
        nodes = payload.get("nodes") or []
        edges = payload.get("edges") or []
        variables = payload.get("variables") or []
        doubts = payload.get("doubts") or []

        # ALWAYS compute tree from nodes/edges - don't rely on frontend
        tree = tree_from_flowchart(nodes, edges)

        # Infer outputs from end nodes if not explicitly provided
        outputs = payload.get("outputs") or []
        if not outputs:
            outputs = _infer_outputs_from_nodes(nodes, output_type)

        # Extract validation metadata
        validation_score = payload.get("validation_score") or 0
        validation_count = payload.get("validation_count") or 0
        is_validated = payload.get("is_validated") or False

        # Peer review: check if user wants to publish to community
        is_published = payload.get("is_published") or False

        # Validate workflow structure before saving
        workflow_to_validate = {
            "nodes": nodes,
            "edges": edges,
            "variables": variables,
        }
        is_valid, validation_errors = _workflow_validator.validate(
            workflow_to_validate, strict=True
        )
        if not is_valid:
            error_message = _workflow_validator.format_errors(validation_errors)
            return JSONResponse(
                {
                    "error": "Workflow validation failed",
                    "message": error_message,
                    "validation_errors": [
                        {"code": e.code, "message": e.message, "node_id": e.node_id}
                        for e in validation_errors
                    ],
                },
                status_code=400,
            )

        try:
            workflow_store.create_workflow(
                workflow_id=workflow_id,
                user_id=user.id,
                name=name,
                description=description,
                domain=domain,
                tags=tags,
                nodes=nodes,
                edges=edges,
                inputs=variables,  # Storage layer uses 'inputs' parameter name
                outputs=outputs,
                tree=tree,
                doubts=doubts,
                validation_score=validation_score,
                validation_count=validation_count,
                is_validated=is_validated,
                output_type=output_type,
                is_published=is_published,
            )
        except sqlite3.IntegrityError:
            # Workflow ID already exists, try updating instead
            success = workflow_store.update_workflow(
                workflow_id=workflow_id,
                user_id=user.id,
                name=name,
                description=description,
                domain=domain,
                tags=tags,
                nodes=nodes,
                edges=edges,
                inputs=variables,  # Storage layer uses 'inputs' parameter name
                outputs=outputs,
                tree=tree,
                doubts=doubts,
                validation_score=validation_score,
                validation_count=validation_count,
                is_validated=is_validated,
                output_type=output_type,
                is_published=is_published,
            )
            if not success:
                return JSONResponse({"error": "Failed to save workflow"}, status_code=500)

        response = {
            "workflow_id": workflow_id,
            "name": name,
            "description": description,
            "domain": domain,
            "tags": tags,
            "output_type": output_type,
            "nodes": nodes,
            "edges": edges,
            "message": "Workflow saved successfully.",
        }
        return JSONResponse(response, status_code=201)

    @router.get("/api/workflows/{workflow_id}")
    async def get_workflow(
        workflow_id: str,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        """Get a specific workflow by ID."""
        workflow = workflow_store.get_workflow(workflow_id, user.id)

        if not workflow:
            return JSONResponse({"error": "Workflow not found"}, status_code=404)

        # Convert to full Workflow format with metadata
        response = {
            "id": workflow.id,
            "output_type": workflow.output_type or "string",
            "metadata": {
                "name": workflow.name,
                "description": workflow.description,
                "domain": workflow.domain,
                "tags": workflow.tags,
                "creator_id": workflow.user_id,
                "created_at": workflow.created_at,
                "updated_at": workflow.updated_at,
                "validation_score": workflow.validation_score,
                "validation_count": workflow.validation_count,
                "confidence": _calculate_confidence(
                    workflow.validation_score, workflow.validation_count
                ),
                "is_validated": workflow.is_validated,
            },
            "nodes": workflow.nodes,
            "edges": workflow.edges,
            "variables": workflow.inputs,  # Storage field is 'inputs', API exposes as 'variables'
            "outputs": workflow.outputs,
            "tree": workflow.tree,
            "doubts": workflow.doubts,
            "build_history": workflow.build_history,
            "building": workflow.building,
            "conversation_id": workflow.conversation_id,
            "uploaded_files": workflow.uploaded_files,
        }
        return JSONResponse(response)

    @router.delete("/api/workflows/{workflow_id}")
    async def delete_workflow(
        workflow_id: str,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        """Delete a workflow."""
        success = workflow_store.delete_workflow(workflow_id, user.id)

        if not success:
            return JSONResponse(
                {"error": "Workflow not found or unauthorized"}, status_code=404
            )

        return JSONResponse({"message": "Workflow deleted successfully"})

    @router.patch("/api/workflows/{workflow_id}")
    async def patch_workflow(
        workflow_id: str,
        request: Request,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        """Incrementally update a workflow without changing draft status.

        Use this for UI-triggered changes (edge labels, node positions, etc.)
        that should be persisted but shouldn't mark the workflow as "saved".

        Unlike PUT, this preserves is_draft status.
        """
        try:
            payload = await request.json()
        except Exception:
            payload = {}

        # Check workflow exists and belongs to user
        existing = workflow_store.get_workflow(workflow_id, user.id)
        if not existing:
            return JSONResponse(
                {"error": "Workflow not found or unauthorized"}, status_code=404
            )

        # Build update kwargs - only include provided fields
        update_kwargs: Dict[str, Any] = {}

        if "nodes" in payload:
            update_kwargs["nodes"] = payload["nodes"]
        if "edges" in payload:
            update_kwargs["edges"] = payload["edges"]
        if "variables" in payload:
            update_kwargs["inputs"] = payload["variables"]

        # If nothing to update, return success immediately
        if not update_kwargs:
            return JSONResponse({"message": "No changes to apply"})

        # Recompute tree if nodes/edges changed
        nodes = update_kwargs.get("nodes") or existing.nodes
        edges = update_kwargs.get("edges") or existing.edges
        update_kwargs["tree"] = tree_from_flowchart(nodes, edges)

        # Attempt the update (preserves is_draft by not passing it)
        try:
            success = workflow_store.update_workflow(
                workflow_id, user.id, **update_kwargs
            )
            if not success:
                return JSONResponse(
                    {"error": "Failed to update workflow"}, status_code=500
                )
        except Exception as e:
            logger.exception("PATCH workflow failed: %s", e)
            return JSONResponse({"error": f"Database error: {e}"}, status_code=500)

        return JSONResponse(
            {
                "workflow_id": workflow_id,
                "message": "Workflow updated successfully",
                "updated_fields": list(update_kwargs.keys()),
            }
        )

    @router.put("/api/workflows/{workflow_id}")
    async def update_workflow(
        workflow_id: str,
        request: Request,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        """Update an existing workflow.

        This also marks the workflow as non-draft (is_draft=False) since
        the user is explicitly saving it.
        """
        try:
            payload = await request.json()
        except Exception:
            payload = {}

        # Check workflow exists and belongs to user
        existing = workflow_store.get_workflow(workflow_id, user.id)
        if not existing:
            return JSONResponse(
                {"error": "Workflow not found or unauthorized"}, status_code=404
            )

        # Extract workflow data from payload
        name = payload.get("name") or existing.name
        description = payload.get("description") or existing.description
        domain = payload.get("domain") or existing.domain
        tags = payload.get("tags") or existing.tags
        output_type = (
            payload.get("output_type") or existing.output_type or "string"
        )

        # Extract workflow structure
        nodes = payload.get("nodes") or existing.nodes
        edges = payload.get("edges") or existing.edges
        variables = payload.get("variables") or existing.inputs
        doubts = payload.get("doubts") or existing.doubts

        # ALWAYS compute tree from nodes/edges
        tree = tree_from_flowchart(nodes, edges)

        # Infer outputs from end nodes using workflow-level output_type
        outputs = payload.get("outputs") or []
        if not outputs:
            outputs = _infer_outputs_from_nodes(nodes, output_type)

        # Extract validation metadata (preserve existing if not provided)
        validation_score = payload.get(
            "validation_score", existing.validation_score
        )
        validation_count = payload.get(
            "validation_count", existing.validation_count
        )
        is_validated = payload.get("is_validated", existing.is_validated)

        # Peer review: check if user wants to publish to community
        is_published = payload.get("is_published", existing.is_published)

        # Validate workflow structure before saving
        workflow_to_validate = {
            "nodes": nodes,
            "edges": edges,
            "variables": variables,
        }
        is_valid, validation_errors = _workflow_validator.validate(
            workflow_to_validate, strict=True
        )
        if not is_valid:
            error_message = _workflow_validator.format_errors(validation_errors)
            return JSONResponse(
                {
                    "error": "Workflow validation failed",
                    "message": error_message,
                    "validation_errors": [
                        {"code": e.code, "message": e.message, "node_id": e.node_id}
                        for e in validation_errors
                    ],
                },
                status_code=400,
            )

        # Update workflow - also marks as non-draft (saved)
        success = workflow_store.update_workflow(
            workflow_id=workflow_id,
            user_id=user.id,
            name=name,
            description=description,
            domain=domain,
            tags=tags,
            nodes=nodes,
            edges=edges,
            inputs=variables,
            outputs=outputs,
            tree=tree,
            doubts=doubts,
            validation_score=validation_score,
            validation_count=validation_count,
            is_validated=is_validated,
            output_type=output_type,
            is_draft=False,  # Explicitly saving marks it as non-draft
            is_published=is_published,
        )

        if not success:
            return JSONResponse({"error": "Failed to update workflow"}, status_code=500)

        response = {
            "workflow_id": workflow_id,
            "name": name,
            "description": description,
            "domain": domain,
            "tags": tags,
            "output_type": output_type,
            "nodes": nodes,
            "edges": edges,
            "message": "Workflow updated successfully.",
        }
        return JSONResponse(response)

    @router.get("/api/uploads/{file_path:path}")
    async def serve_upload(
        file_path: str,
        user: AuthUser = Depends(require_auth),
    ) -> FileResponse:
        """Serve an uploaded file from the data directory.

        Only serves files under the uploads/ subdirectory to prevent
        path traversal attacks.
        """
        data_dir = lemon_data_dir(repo_root)
        resolved = (data_dir / file_path).resolve()
        # Guard: must be inside the data directory
        if not str(resolved).startswith(str(data_dir.resolve())):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        if not resolved.is_file():
            return JSONResponse({"error": "file not found"}, status_code=404)
        return FileResponse(resolved)

    app.include_router(router)
