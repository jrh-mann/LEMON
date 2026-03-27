from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, FastAPI, Request
from starlette.responses import JSONResponse

from ..deps import optional_auth, require_auth
from ...storage.auth import AuthUser
from ...storage.workflows import WorkflowStore
from ...workflow_package_service import WorkflowPackageService
from ...workflow_transfer import WorkflowTransferError, build_package_bundle_bytes


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
                "building": workflow.building,
                "invalid_public": not workflow.is_validated,
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


def _collect_package_external_subflows(
    workflow_store: WorkflowStore,
    *,
    user_id: str,
    entry_workflow_ids: List[str],
    package_member_ids: Set[str],
) -> List[str]:
    """Find subprocess references reachable from package members that are outside package membership."""
    visited: Set[str] = set()
    stack = list(entry_workflow_ids)
    external_ids: Set[str] = set()

    while stack:
        workflow_id = stack.pop()
        if workflow_id in visited:
            continue
        visited.add(workflow_id)

        workflow = workflow_store.get_workflow(workflow_id, user_id)
        if workflow is None:
            continue

        for node in workflow.nodes:
            if node.get("type") != "subprocess":
                continue
            sub_id = node.get("subworkflow_id")
            if not isinstance(sub_id, str) or not sub_id:
                continue
            if sub_id in package_member_ids:
                if sub_id not in visited:
                    stack.append(sub_id)
            else:
                external_ids.add(sub_id)

    return sorted(external_ids)


def _format_external_subflow_warning(external_ids: List[str]) -> str:
    return (
        "Package export included subflows outside package membership: "
        + ", ".join(external_ids)
        + "."
    )


def _strip_imports_and_main(code: str) -> str:
    lines = code.splitlines()
    stripped: List[str] = []
    in_main_block = False

    for line in lines:
        if line.startswith('if __name__ == "__main__":'):
            in_main_block = True
            continue
        if in_main_block:
            continue
        if line.startswith("import ") or line.startswith("from "):
            continue
        stripped.append(line)

    return "\n".join(stripped).strip()


def _insert_before_main_block(code: str, extra_block: str) -> str:
    if not extra_block.strip():
        return code

    marker = '\nif __name__ == "__main__":'
    idx = code.find(marker)
    if idx == -1:
        if code.endswith("\n"):
            return code + "\n" + extra_block
        return code + "\n\n" + extra_block

    return code[:idx].rstrip() + "\n\n" + extra_block + code[idx:]


def _compile_package_members_to_python(
    *,
    package_name: str,
    head_workflow,
    member_workflows: Dict[str, Any],
    include_main: bool,
    fetch_subworkflow,
) -> tuple[Any, List[str], List[str]]:
    from ...execution.python_compiler import PythonCodeGenerator

    processed_subflows: Set[str] = set()
    head_generator = PythonCodeGenerator(
        nodes=head_workflow.nodes,
        edges=head_workflow.edges,
        variables=head_workflow.inputs,
        outputs=head_workflow.outputs,
        workflow_name=package_name or head_workflow.name,
        include_main=include_main,
        fetch_subworkflow=fetch_subworkflow,
        _processed_subflows=processed_subflows,
    )
    head_result = head_generator.compile()
    if not head_result.success or not head_result.code:
        return head_result, [], sorted(processed_subflows)

    extra_blocks: List[str] = []
    compiled_member_ids = sorted(processed_subflows)
    for workflow_id, workflow in member_workflows.items():
        if workflow_id == head_workflow.id or workflow_id in processed_subflows:
            continue

        member_generator = PythonCodeGenerator(
            nodes=workflow.nodes,
            edges=workflow.edges,
            variables=workflow.inputs,
            outputs=workflow.outputs,
            workflow_name=f"subflow_{workflow_id.replace('-', '_')}",
            include_main=False,
            fetch_subworkflow=fetch_subworkflow,
            _processed_subflows=processed_subflows,
        )
        member_result = member_generator.compile()
        head_result.warnings.extend(
            [f"Member {workflow_id}: {warning}" for warning in member_result.warnings]
        )
        head_result.partial_failure = (
            head_result.partial_failure or member_result.partial_failure
        )
        if member_result.success and member_result.code:
            extra_blocks.append(_strip_imports_and_main(member_result.code))
            compiled_member_ids.append(workflow_id)
        elif member_result.error:
            head_result.success = False
            head_result.error = member_result.error
            return (
                head_result,
                extra_blocks,
                sorted(set(compiled_member_ids + list(processed_subflows))),
            )

    if extra_blocks:
        head_result.code = _insert_before_main_block(
            head_result.code,
            "\n\n".join(block for block in extra_blocks if block.strip()),
        )

    return (
        head_result,
        extra_blocks,
        sorted(set(compiled_member_ids + list(processed_subflows))),
    )


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

    @router.get("/api/packages/public/{package_id}")
    async def get_public_package(
        package_id: str, user: AuthUser | None = Depends(optional_auth)
    ) -> JSONResponse:
        try:
            package, owner_id = service._require_any_package(package_id)
        except ValueError:
            return JSONResponse({"error": "Package not found"}, status_code=404)
        if not package.is_published:
            return JSONResponse({"error": "Package not published"}, status_code=404)
        body = _serialize_package(package, workflow_store, owner_id)
        body["user_vote"] = (
            service.package_store.get_user_vote(package.id, user.id) if user else None
        )
        body["is_publishable"] = False
        return JSONResponse(body)

    @router.get("/api/packages/public/{package_id}/workflows/{workflow_id}")
    async def get_public_package_workflow(
        package_id: str,
        workflow_id: str,
        user: AuthUser | None = Depends(optional_auth),
    ) -> JSONResponse:
        try:
            package, owner_id = service._require_any_package(package_id)
        except ValueError:
            return JSONResponse({"error": "Package not found"}, status_code=404)
        if not package.is_published:
            return JSONResponse({"error": "Package not published"}, status_code=404)
        member_ids = {member.workflow_id for member in package.members}
        if workflow_id not in member_ids:
            return JSONResponse(
                {"error": "Workflow is not part of this package"}, status_code=404
            )
        workflow = workflow_store.get_workflow(workflow_id, owner_id)
        if workflow is None:
            return JSONResponse({"error": "Workflow not found"}, status_code=404)
        return JSONResponse(
            {
                "id": workflow.id,
                "output_type": workflow.output_type or "string",
                "metadata": {
                    "name": workflow.name,
                    "description": workflow.description,
                    "domain": workflow.domain,
                    "tags": workflow.tags,
                    "created_at": workflow.created_at,
                    "updated_at": workflow.updated_at,
                    "confidence": "none",
                    "is_validated": workflow.is_validated,
                },
                "nodes": workflow.nodes,
                "edges": workflow.edges,
                "variables": workflow.inputs,
                "outputs": workflow.outputs,
                "tree": workflow.tree,
                "review_status": package.review_status,
                "net_votes": package.net_votes,
                "published_at": package.published_at,
                "package_id": package.id,
                "read_only": True,
            }
        )

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
        success = service.delete_package(user.id, package_id)
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
        package_id: str, request: Request, user: AuthUser = Depends(require_auth)
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError):
            payload = {}
        try:
            package = service.publish_package(
                user.id,
                package_id,
                force_publish=bool(payload.get("force_publish", False)),
            )
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

    @router.get("/api/packages/{package_id}/export-bundle")
    async def export_package_bundle(
        package_id: str, user: AuthUser = Depends(require_auth)
    ) -> JSONResponse:
        try:
            bundle_bytes, warnings = build_package_bundle_bytes(
                workflow_store, user, package_id
            )
        except WorkflowTransferError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(
            {
                "content": bundle_bytes.decode("latin1"),
                "warnings": warnings,
            }
        )

    @router.post("/api/packages/{package_id}/compile-python")
    async def compile_package_to_python(
        package_id: str,
        request: Request,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        package = service.get_package(user.id, package_id)
        if package is None:
            return JSONResponse(
                {
                    "success": False,
                    "code": None,
                    "warnings": [],
                    "error": "Package not found",
                },
                status_code=404,
            )
        if not package.head_workflow_id:
            return JSONResponse(
                {
                    "success": False,
                    "code": None,
                    "warnings": [],
                    "error": "Package has no head workflow",
                },
                status_code=400,
            )

        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError):
            payload = {}

        include_imports = payload.get("include_imports", True)
        include_docstring = payload.get("include_docstring", True)
        include_main = payload.get("include_main", True)
        include_external_subflows = bool(
            payload.get("include_external_subflows", False)
        )
        _ = (include_imports, include_docstring)

        package_member_ids = {member.workflow_id for member in package.members}
        member_workflows = {
            member.workflow_id: workflow_store.get_workflow(member.workflow_id, user.id)
            for member in package.members
        }
        head_workflow = workflow_store.get_workflow(package.head_workflow_id, user.id)
        if head_workflow is None:
            return JSONResponse(
                {
                    "success": False,
                    "code": None,
                    "warnings": [],
                    "error": "Head workflow not found",
                },
                status_code=404,
            )

        external_subflow_ids = _collect_package_external_subflows(
            workflow_store,
            user_id=user.id,
            entry_workflow_ids=list(package_member_ids),
            package_member_ids=package_member_ids,
        )
        if external_subflow_ids and not include_external_subflows:
            return JSONResponse(
                {
                    "success": False,
                    "code": None,
                    "warnings": [],
                    "error": (
                        "Package references subflows outside package membership."
                    ),
                    "requires_confirmation": True,
                    "external_subflow_ids": external_subflow_ids,
                    "partial_failure": False,
                }
            )

        included_external_subflow_ids: Set[str] = set()

        def _fetch_subworkflow(sub_id: str):
            if sub_id not in package_member_ids:
                included_external_subflow_ids.add(sub_id)
                if not include_external_subflows:
                    return None
            return workflow_store.get_workflow(sub_id, user.id)

        result, _, compiled_member_ids = _compile_package_members_to_python(
            package_name=package.name or head_workflow.name,
            head_workflow=head_workflow,
            member_workflows={
                workflow_id: workflow
                for workflow_id, workflow in member_workflows.items()
                if workflow is not None
            },
            include_main=include_main,
            fetch_subworkflow=_fetch_subworkflow,
        )

        warnings = list(result.warnings)
        included_external = sorted(included_external_subflow_ids)
        if included_external:
            warnings.append(_format_external_subflow_warning(included_external))
        missing_member_ids = sorted(
            workflow_id
            for workflow_id, workflow in member_workflows.items()
            if workflow is None
        )
        if missing_member_ids:
            warnings.append(
                "Package members missing during Python export: "
                + ", ".join(missing_member_ids)
                + "."
            )
        uncompiled_member_ids = sorted(
            workflow_id
            for workflow_id in package_member_ids
            if workflow_id != head_workflow.id
            and workflow_id not in compiled_member_ids
            and workflow_id not in missing_member_ids
        )
        if uncompiled_member_ids:
            warnings.append(
                "Package members were not emitted as standalone functions: "
                + ", ".join(uncompiled_member_ids)
                + "."
            )

        if result.success:
            return JSONResponse(
                {
                    "success": True,
                    "code": result.code,
                    "warnings": warnings,
                    "partial_failure": result.partial_failure,
                    "external_subflow_ids": included_external,
                }
            )

        return JSONResponse(
            {
                "success": False,
                "error": result.error,
                "code": None,
                "warnings": warnings,
                "partial_failure": result.partial_failure,
                "external_subflow_ids": included_external,
            },
            status_code=400,
        )

    @router.post("/api/packages/{package_id}/clone")
    async def clone_package(
        package_id: str, user: AuthUser = Depends(require_auth)
    ) -> JSONResponse:
        try:
            cloned = service.clone_package(package_id, user.id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(
            _serialize_package(cloned, workflow_store, user.id), status_code=201
        )

    app.include_router(router)
