"""Workflow import/export helpers for single JSON and zip bundles."""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from .storage.auth import AuthUser
from .storage.workflows import WorkflowRecord, WorkflowStore
from .subflow_cycles import detect_subflow_cycles
from .tools.constants import generate_workflow_id
from .utils.flowchart import tree_from_flowchart
from .validation.workflow_validator import WorkflowValidator


BUNDLE_FORMAT = "lemon-workflow-bundle"
BUNDLE_VERSION = 1


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
) -> Tuple[str, int]:
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            raw_manifest = _read_zip_json(zf, "manifest.json")
            if raw_manifest.get("format") != BUNDLE_FORMAT:
                raise WorkflowTransferError("Invalid bundle format")
            if raw_manifest.get("version") != BUNDLE_VERSION:
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

            validated_payloads: List[Tuple[Dict[str, Any], bool]] = []
            for payload in normalized_payloads:
                is_validated = _validate_import_payload(
                    payload, force_import=force_import
                )
                validated_payloads.append((payload, is_validated))
            for payload, is_validated in validated_payloads:
                _persist_imported_workflow(
                    workflow_store,
                    user,
                    payload,
                    is_validated=is_validated,
                )

            return id_map[entry_workflow_id], len(normalized_payloads)
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
