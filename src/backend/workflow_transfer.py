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
    }


def build_workflow_bundle_bytes(
    workflow_store: WorkflowStore,
    user: AuthUser,
    root_workflow_id: str,
) -> Tuple[bytes, List[str]]:
    records = _collect_workflow_bundle(workflow_store, user, root_workflow_id)
    warnings = detect_subflow_cycles(
        records[0].nodes if records else [],
        lambda workflow_id: workflow_store.get_workflow(workflow_id, user.id),
    )
    manifest = {
        "version": BUNDLE_VERSION,
        "format": BUNDLE_FORMAT,
        "entry_workflow_id": root_workflow_id,
        "workflow_ids": [record.id for record in records],
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
) -> str:
    imported = _normalize_imported_workflow(payload, generate_workflow_id())
    _validate_import_payload(imported)
    _persist_imported_workflow(workflow_store, user, imported)
    return imported["id"]


def import_workflow_bundle_zip(
    workflow_store: WorkflowStore,
    user: AuthUser,
    zip_bytes: bytes,
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

            for payload in normalized_payloads:
                _validate_import_payload(payload)
            for payload in normalized_payloads:
                _persist_imported_workflow(workflow_store, user, payload)

            return id_map[entry_workflow_id], len(normalized_payloads)
    except zipfile.BadZipFile as exc:
        raise WorkflowTransferError("Invalid zip file") from exc


def _collect_workflow_bundle(
    workflow_store: WorkflowStore,
    user: AuthUser,
    root_workflow_id: str,
) -> List[WorkflowRecord]:
    visited: Set[str] = set()
    ordered: List[WorkflowRecord] = []
    stack = [root_workflow_id]

    while stack:
        workflow_id = stack.pop()
        if workflow_id in visited:
            continue
        record = workflow_store.get_workflow(workflow_id, user.id)
        if record is None:
            raise WorkflowTransferError(f"Subworkflow '{workflow_id}' not found")
        visited.add(workflow_id)
        ordered.append(record)

        for node in record.nodes:
            if node.get("type") == "subprocess" and node.get("subworkflow_id"):
                stack.append(node["subworkflow_id"])

    return ordered


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

    metadata = (
        payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
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


def _validate_import_payload(payload: Dict[str, Any]) -> None:
    validator = WorkflowValidator()
    workflow = {
        "nodes": payload["nodes"],
        "edges": payload["edges"],
        "variables": payload["variables"],
    }
    valid, errors = validator.validate(workflow, strict=True)
    if not valid:
        first = errors[0]
        raise WorkflowTransferError(first.message)


def _persist_imported_workflow(
    workflow_store: WorkflowStore,
    user: AuthUser,
    payload: Dict[str, Any],
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
        is_validated=False,
        output_type=payload["output_type"],
        is_draft=False,
    )
