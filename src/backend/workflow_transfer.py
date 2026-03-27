"""Workflow import/export helpers for single JSON and zip bundles."""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from .storage.auth import AuthUser
from .storage.packages import PackageStore
from .storage.workflows import WorkflowRecord, WorkflowStore
from .subflow_cycles import detect_subflow_cycles
from .tools.constants import generate_workflow_id
from .utils.flowchart import tree_from_flowchart
from .validation.workflow_validator import WorkflowValidator


BUNDLE_FORMAT = "lemon-workflow-bundle"
BUNDLE_VERSION = 2


class WorkflowTransferError(ValueError):
    """Raised when import/export payloads are invalid."""


class WorkflowImportValidationError(WorkflowTransferError):
    """Raised when import payload is well-formed but fails workflow validation."""

    def __init__(self, errors: List[Dict[str, Any]], message: str):
        super().__init__(message)
        self.errors = errors
        self.message = message


@dataclass
class ImportedWorkflow:
    old_id: str
    new_id: str
    payload: Dict[str, Any]


@dataclass(frozen=True)
class PackageImportPlan:
    name: str
    description: str
    old_head_workflow_id: str
    member_roles: Dict[str, str]


@dataclass(frozen=True)
class BundleImportResult:
    workflow_id: str
    imported_count: int
    imported_kind: str
    package_id: Optional[str] = None


def serialize_workflow_record(record: WorkflowRecord) -> Dict[str, Any]:
    return {
        "id": record.id,
        "metadata": {
            "name": record.name,
            "description": record.description,
            "domain": record.domain,
            "tags": record.tags,
            "creator_id": record.user_id,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "confidence": "none",
            "is_validated": record.is_validated,
        },
        "flowchart": {
            "nodes": record.nodes,
            "edges": record.edges,
        },
        "variables": record.inputs,
        "outputs": record.outputs,
        "output_type": record.output_type or "string",
        "package": {
            "id": record.package_id,
            "name": record.package_name,
            "role": record.package_role,
            "head_workflow_id": record.package_head_workflow_id,
        },
    }


def build_workflow_bundle_bytes(
    workflow_store: WorkflowStore,
    user: AuthUser,
    root_workflow_id: str,
) -> Tuple[bytes, List[str]]:
    records, missing_workflow_ids = _collect_workflow_bundle(
        workflow_store, user, root_workflow_id
    )
    warnings = detect_subflow_cycles(
        records[0].nodes if records else [],
        lambda workflow_id: workflow_store.get_workflow(workflow_id, user.id),
    )
    warnings.extend(
        [
            f"Subworkflow '{workflow_id}' could not be fetched and was omitted from the bundle. "
            "Import or execution may fail unless the missing workflow is restored."
            for workflow_id in missing_workflow_ids
        ]
    )
    manifest = {
        "version": BUNDLE_VERSION,
        "format": BUNDLE_FORMAT,
        "entry_workflow_id": root_workflow_id,
        "workflow_ids": [record.id for record in records],
        "missing_workflow_ids": missing_workflow_ids,
    }
    root_record = records[0] if records else None
    if root_record and root_record.package_id:
        package_description = ""
        package = PackageStore(workflow_store.db_path).get_package(
            root_record.package_id, user.id
        )
        if package is not None:
            package_description = package.description
        manifest["package"] = {
            "id": root_record.package_id,
            "name": root_record.package_name,
            "description": package_description,
            "head_workflow_id": root_record.package_head_workflow_id or root_record.id,
            "members": [
                {
                    "workflow_id": record.id,
                    "role": record.package_role
                    or (
                        "head"
                        if record.id == root_record.package_head_workflow_id
                        else "dependency"
                    ),
                }
                for record in records
                if record.package_id == root_record.package_id
            ],
        }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        for record in records:
            zf.writestr(
                f"workflows/{record.id}.json",
                json.dumps(serialize_workflow_record(record), indent=2),
            )
        for missing_id in missing_workflow_ids:
            zf.writestr(
                f"workflows/{missing_id}.json",
                json.dumps(
                    _build_missing_subworkflow_placeholder(missing_id), indent=2
                ),
            )
    return buffer.getvalue(), warnings


def build_package_bundle_bytes(
    workflow_store: WorkflowStore,
    user: AuthUser,
    package_id: str,
) -> Tuple[bytes, List[str]]:
    package_store = PackageStore(workflow_store.db_path)
    package = package_store.get_package(package_id, user.id)
    if package is None:
        raise WorkflowTransferError("Package not found")
    if not package.head_workflow_id:
        raise WorkflowTransferError("Package has no head workflow")

    records = []
    missing_workflow_ids: List[str] = []
    for member in package.members:
        record = workflow_store.get_workflow(member.workflow_id, user.id)
        if record is None:
            missing_workflow_ids.append(member.workflow_id)
            continue
        records.append(record)

    warnings = []
    manifest = {
        "version": BUNDLE_VERSION,
        "format": BUNDLE_FORMAT,
        "entry_workflow_id": package.head_workflow_id,
        "workflow_ids": [record.id for record in records],
        "missing_workflow_ids": missing_workflow_ids,
        "package": {
            "id": package.id,
            "name": package.name,
            "description": package.description,
            "head_workflow_id": package.head_workflow_id,
            "members": [
                {"workflow_id": member.workflow_id, "role": member.role}
                for member in package.members
            ],
        },
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        for record in records:
            zf.writestr(
                f"workflows/{record.id}.json",
                json.dumps(serialize_workflow_record(record), indent=2),
            )
    return buffer.getvalue(), warnings


def import_single_workflow_json(
    workflow_store: WorkflowStore,
    user: AuthUser,
    payload: Dict[str, Any],
    force_import: bool = False,
) -> str:
    imported = _normalize_imported_workflow(payload, generate_workflow_id())
    is_validated = _validate_import_payload(imported, force_import=force_import)
    _persist_imported_workflow(
        workflow_store, user, imported, is_validated=is_validated
    )
    return imported["id"]


def import_workflow_bundle_zip(
    workflow_store: WorkflowStore,
    user: AuthUser,
    zip_bytes: bytes,
    force_import: bool = False,
) -> BundleImportResult:
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            raw_manifest = _read_zip_json(zf, "manifest.json")
            if raw_manifest.get("format") != BUNDLE_FORMAT:
                raise WorkflowTransferError("Invalid bundle format")
            manifest_version = raw_manifest.get("version")
            if manifest_version not in (1, BUNDLE_VERSION):
                raise WorkflowTransferError("Unsupported bundle version")

            workflow_ids = raw_manifest.get("workflow_ids")
            entry_workflow_id = raw_manifest.get("entry_workflow_id")
            if not isinstance(workflow_ids, list) or not workflow_ids:
                raise WorkflowTransferError("Bundle manifest missing workflow_ids")
            if (
                not isinstance(entry_workflow_id, str)
                or entry_workflow_id not in workflow_ids
            ):
                raise WorkflowTransferError(
                    "Bundle manifest has invalid entry_workflow_id"
                )

            normalized_payloads: List[Dict[str, Any]] = []
            id_map: Dict[str, str] = {
                old_id: generate_workflow_id() for old_id in workflow_ids
            }
            for old_id in workflow_ids:
                payload = _read_zip_json(zf, f"workflows/{old_id}.json")
                normalized = _normalize_imported_workflow(payload, id_map[old_id])
                normalized_payloads.append(normalized)

            _rewrite_bundle_references(normalized_payloads, id_map)
            package_plan = _build_package_import_plan(raw_manifest)

            validated_payloads: List[Tuple[Dict[str, Any], bool]] = []
            for payload in normalized_payloads:
                is_validated = _validate_import_payload(
                    payload, force_import=force_import
                )
                validated_payloads.append((payload, is_validated))

            package_store = PackageStore(workflow_store.db_path)
            created_package_id: Optional[str] = None
            created_workflow_ids: List[str] = []
            try:
                if package_plan is not None:
                    created_package = package_store.create_package(
                        user.id,
                        name=package_plan.name,
                        description=package_plan.description,
                    )
                    created_package_id = created_package.id
                    _rewrite_bundle_package_metadata(
                        normalized_payloads,
                        package_id=created_package_id,
                        package_name=package_plan.name,
                        new_head_id=id_map[package_plan.old_head_workflow_id],
                        member_roles=package_plan.member_roles,
                    )

                for payload, is_validated in validated_payloads:
                    _persist_imported_workflow(
                        workflow_store,
                        user,
                        payload,
                        is_validated=is_validated,
                    )
                    created_workflow_ids.append(payload["id"])

                if package_plan is not None and created_package_id is not None:
                    for old_workflow_id, role in package_plan.member_roles.items():
                        new_workflow_id = id_map.get(old_workflow_id)
                        if new_workflow_id is None:
                            continue
                        package_store.add_workflow_to_package(
                            created_package_id,
                            new_workflow_id,
                            role=role,
                        )
                    package_store.update_package(
                        created_package_id,
                        user.id,
                        head_workflow_id=id_map[package_plan.old_head_workflow_id],
                    )

                return BundleImportResult(
                    workflow_id=id_map[entry_workflow_id],
                    imported_count=len(normalized_payloads),
                    imported_kind=(
                        "package_bundle"
                        if created_package_id is not None
                        else "workflow_bundle"
                    ),
                    package_id=created_package_id,
                )
            except Exception:
                for created_workflow_id in reversed(created_workflow_ids):
                    workflow_store.delete_workflow(created_workflow_id, user.id)
                if created_package_id is not None:
                    package_store.delete_package(created_package_id, user.id)
                raise
    except zipfile.BadZipFile as exc:
        raise WorkflowTransferError("Invalid zip file") from exc


def _collect_workflow_bundle(
    workflow_store: WorkflowStore,
    user: AuthUser,
    root_workflow_id: str,
) -> Tuple[List[WorkflowRecord], List[str]]:
    visited: Set[str] = set()
    ordered: List[WorkflowRecord] = []
    missing: List[str] = []
    stack = [root_workflow_id]

    while stack:
        workflow_id = stack.pop()
        if workflow_id in visited:
            continue
        record = workflow_store.get_workflow(workflow_id, user.id)
        if record is None:
            if workflow_id not in missing:
                missing.append(workflow_id)
            continue
        visited.add(workflow_id)
        ordered.append(record)

        for node in record.nodes:
            if node.get("type") == "subprocess" and node.get("subworkflow_id"):
                stack.append(node["subworkflow_id"])

    if not ordered:
        raise WorkflowTransferError(f"Subworkflow '{root_workflow_id}' not found")

    return ordered, missing


def _read_zip_json(zf: zipfile.ZipFile, filename: str) -> Dict[str, Any]:
    try:
        with zf.open(filename) as fh:
            return json.loads(fh.read().decode("utf-8"))
    except KeyError as exc:
        raise WorkflowTransferError(f"Bundle missing '{filename}'") from exc
    except json.JSONDecodeError as exc:
        raise WorkflowTransferError(f"Invalid JSON in '{filename}'") from exc


def _normalize_imported_workflow(
    payload: Dict[str, Any], new_id: str
) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise WorkflowTransferError("Invalid workflow JSON")
    flowchart = payload.get("flowchart")
    if not isinstance(flowchart, dict):
        raise WorkflowTransferError(
            "Invalid format: JSON must have a 'flowchart' object"
        )
    nodes = flowchart.get("nodes")
    if not isinstance(nodes, list):
        raise WorkflowTransferError(
            "Invalid format: JSON must have a 'flowchart.nodes' array"
        )
    edges = flowchart.get("edges") or []
    if not isinstance(edges, list):
        raise WorkflowTransferError(
            "Invalid format: JSON must have a 'flowchart.edges' array"
        )

    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    if metadata.get("is_placeholder") is True:
        raise WorkflowTransferError(
            "Cannot import placeholder workflow for missing subflow"
        )
    variables = payload.get("variables")
    if variables is None:
        variables = flowchart.get("variables", [])
    outputs = payload.get("outputs")
    if outputs is None:
        outputs = flowchart.get("outputs", [])

    return {
        "id": new_id,
        "old_id": str(payload.get("id") or ""),
        "metadata": metadata,
        "nodes": nodes,
        "edges": edges,
        "variables": variables if isinstance(variables, list) else [],
        "outputs": outputs if isinstance(outputs, list) else [],
        "output_type": payload.get("output_type")
        if isinstance(payload.get("output_type"), str)
        else "string",
        "package": payload.get("package")
        if isinstance(payload.get("package"), dict)
        else {},
    }


def _build_missing_subworkflow_placeholder(workflow_id: str) -> Dict[str, Any]:
    return {
        "id": workflow_id,
        "metadata": {
            "name": "Missing Subworkflow",
            "description": "Placeholder exported because the referenced subworkflow could not be fetched.",
            "tags": [],
            "is_placeholder": True,
            "placeholder_reason": "missing_subworkflow",
        },
        "flowchart": {
            "nodes": [],
            "edges": [],
        },
        "variables": [],
        "outputs": [],
        "output_type": "string",
    }


def _rewrite_bundle_references(
    payloads: List[Dict[str, Any]], id_map: Dict[str, str]
) -> None:
    known_old_ids = set(id_map.keys())
    for payload in payloads:
        for node in payload["nodes"]:
            if node.get("type") == "subprocess":
                sub_id = node.get("subworkflow_id")
                if sub_id not in known_old_ids:
                    raise WorkflowTransferError(
                        f"Bundle references missing subworkflow '{sub_id}'"
                    )
                node["subworkflow_id"] = id_map[sub_id]
        for variable in payload["variables"]:
            sub_id = variable.get("subworkflow_id")
            if sub_id in id_map:
                variable["subworkflow_id"] = id_map[sub_id]


def _build_package_import_plan(
    raw_manifest: Dict[str, Any],
) -> Optional[PackageImportPlan]:
    package = raw_manifest.get("package")
    if not isinstance(package, dict):
        return None

    members = package.get("members")
    if not isinstance(members, list):
        return None

    member_roles: Dict[str, str] = {}
    for entry in members:
        if not isinstance(entry, dict):
            continue
        workflow_id = entry.get("workflow_id")
        if not isinstance(workflow_id, str):
            continue
        role = entry.get("role")
        member_roles[workflow_id] = role if isinstance(role, str) else "dependency"
    package_name = str(package.get("name") or "")
    package_description = str(package.get("description") or "")
    old_head_id = package.get("head_workflow_id")
    if (
        not member_roles
        or not isinstance(old_head_id, str)
        or old_head_id not in member_roles
    ):
        return None

    normalized_roles: Dict[str, str] = {
        workflow_id: (role if role in {"head", "dependency"} else "dependency")
        for workflow_id, role in member_roles.items()
    }
    normalized_roles[old_head_id] = "head"

    return PackageImportPlan(
        name=package_name,
        description=package_description,
        old_head_workflow_id=old_head_id,
        member_roles=normalized_roles,
    )


def _rewrite_bundle_package_metadata(
    payloads: List[Dict[str, Any]],
    *,
    package_id: str,
    package_name: str,
    new_head_id: str,
    member_roles: Dict[str, str],
) -> None:

    for payload in payloads:
        old_id = payload.get("old_id")
        if old_id not in member_roles:
            continue
        payload["package"] = {
            "id": package_id,
            "name": package_name,
            "role": member_roles[old_id],
            "head_workflow_id": new_head_id,
        }


def _validate_import_payload(payload: Dict[str, Any], *, force_import: bool) -> bool:
    validator = WorkflowValidator()
    workflow = {
        "nodes": payload["nodes"],
        "edges": payload["edges"],
        "variables": payload["variables"],
    }
    valid, errors = validator.validate(workflow, strict=True)
    if valid:
        return True

    error_payload = [
        {"code": error.code, "message": error.message, "node_id": error.node_id}
        for error in errors
    ]
    if force_import:
        return False

    raise WorkflowImportValidationError(
        error_payload,
        validator.format_errors(errors),
    )


def _persist_imported_workflow(
    workflow_store: WorkflowStore,
    user: AuthUser,
    payload: Dict[str, Any],
    *,
    is_validated: bool,
) -> None:
    metadata = payload["metadata"]
    workflow_store.create_workflow(
        workflow_id=payload["id"],
        user_id=user.id,
        name=str(metadata.get("name") or "Imported Workflow"),
        description=str(metadata.get("description") or ""),
        domain=metadata.get("domain"),
        tags=metadata.get("tags") if isinstance(metadata.get("tags"), list) else [],
        nodes=payload["nodes"],
        edges=payload["edges"],
        inputs=payload["variables"],
        outputs=payload["outputs"],
        tree=tree_from_flowchart(payload["nodes"], payload["edges"]),
        doubts=[],
        is_validated=is_validated,
        output_type=payload["output_type"],
        is_draft=False,
        package_id=payload["package"].get("id"),
        package_name=payload["package"].get("name"),
        package_role=payload["package"].get("role"),
        package_head_workflow_id=payload["package"].get("head_workflow_id"),
    )
