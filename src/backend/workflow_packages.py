from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set
from uuid import uuid4

from .storage.workflows import WorkflowRecord, WorkflowStore


@dataclass(frozen=True)
class PackageDependencyReport:
    package_id: str
    package_name: str
    head_workflow_id: str
    member_workflow_ids: List[str]
    external_dependency_ids: List[str]
    missing_dependency_ids: List[str]


def build_package_report(
    workflow_store: WorkflowStore,
    *,
    user_id: str,
    head_workflow_id: str,
    package_id: Optional[str] = None,
    package_name: Optional[str] = None,
) -> PackageDependencyReport:
    head = workflow_store.get_workflow(head_workflow_id, user_id)
    if head is None:
        raise ValueError(f"Workflow '{head_workflow_id}' not found")

    resolved_package_id = package_id or head.package_id or f"pkg_{uuid4().hex}"
    resolved_package_name = package_name or head.package_name or head.name
    visited: Set[str] = set()
    stack = [head_workflow_id]
    members: List[str] = []
    external: List[str] = []
    missing: List[str] = []

    while stack:
        workflow_id = stack.pop()
        if workflow_id in visited:
            continue
        visited.add(workflow_id)

        record = workflow_store.get_workflow(workflow_id, user_id)
        if record is None:
            if workflow_id not in missing:
                missing.append(workflow_id)
            continue

        if workflow_id != head_workflow_id and record.package_id not in (
            None,
            resolved_package_id,
        ):
            if workflow_id not in external:
                external.append(workflow_id)
            continue

        members.append(workflow_id)

        for node in record.nodes:
            sub_id = node.get("subworkflow_id")
            if node.get("type") == "subprocess" and isinstance(sub_id, str) and sub_id:
                stack.append(sub_id)

    return PackageDependencyReport(
        package_id=resolved_package_id,
        package_name=resolved_package_name,
        head_workflow_id=head_workflow_id,
        member_workflow_ids=members,
        external_dependency_ids=external,
        missing_dependency_ids=missing,
    )


def apply_package_report(
    workflow_store: WorkflowStore,
    *,
    user_id: str,
    report: PackageDependencyReport,
) -> None:
    current_workflows, _ = workflow_store.list_workflows(user_id, limit=1000, offset=0)
    current_member_ids = {
        workflow.id
        for workflow in current_workflows
        if workflow.package_id == report.package_id
    }
    target_member_ids = set(report.member_workflow_ids)

    for workflow_id in current_member_ids - target_member_ids:
        workflow_store.update_workflow(
            workflow_id=workflow_id,
            user_id=user_id,
            package_id="",
            package_name="",
            package_role="",
            package_head_workflow_id="",
        )

    for workflow_id in report.member_workflow_ids:
        workflow_store.update_workflow(
            workflow_id=workflow_id,
            user_id=user_id,
            package_id=report.package_id,
            package_name=report.package_name,
            package_role="head"
            if workflow_id == report.head_workflow_id
            else "dependency",
            package_head_workflow_id=report.head_workflow_id,
        )


def summarize_package_report(
    report: PackageDependencyReport,
    workflow_lookup: Dict[str, WorkflowRecord],
) -> Dict[str, object]:
    return {
        "package_id": report.package_id,
        "package_name": report.package_name,
        "head_workflow_id": report.head_workflow_id,
        "member_count": len(report.member_workflow_ids),
        "members": [
            {
                "workflow_id": workflow_id,
                "name": workflow_lookup[workflow_id].name,
                "role": "head"
                if workflow_id == report.head_workflow_id
                else "dependency",
            }
            for workflow_id in report.member_workflow_ids
            if workflow_id in workflow_lookup
        ],
        "external_dependency_ids": report.external_dependency_ids,
        "missing_dependency_ids": report.missing_dependency_ids,
    }
