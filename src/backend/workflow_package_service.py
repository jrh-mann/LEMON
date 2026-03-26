from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from .storage.packages import PackageStore, WorkflowPackageRecord
from .storage.workflows import WorkflowRecord, WorkflowStore


@dataclass(frozen=True)
class PackageIssue:
    code: str
    message: str
    workflow_id: Optional[str] = None


class WorkflowPackageService:
    def __init__(self, workflow_store: WorkflowStore):
        self.workflow_store = workflow_store
        self.package_store = PackageStore(workflow_store.db_path)

    def create_package(
        self, user_id: str, *, name: str = "", description: str = ""
    ) -> WorkflowPackageRecord:
        return self.package_store.create_package(
            user_id, name=name, description=description
        )

    def list_packages(self, user_id: str) -> List[WorkflowPackageRecord]:
        return self.package_store.list_packages(user_id)

    def get_package(
        self, user_id: str, package_id: str
    ) -> Optional[WorkflowPackageRecord]:
        return self.package_store.get_package(package_id, user_id)

    def add_workflow(
        self, user_id: str, package_id: str, workflow_id: str
    ) -> WorkflowPackageRecord:
        package = self._require_package(user_id, package_id)
        workflow = self._require_workflow(user_id, workflow_id)
        existing_package_id = self.package_store.get_workflow_package_id(workflow_id)
        if existing_package_id and existing_package_id != package_id:
            self.move_workflow(user_id, workflow_id, existing_package_id, package_id)
        else:
            role = "head" if not package.head_workflow_id else "dependency"
            self.package_store.add_workflow_to_package(
                package_id, workflow_id, role=role
            )
            if not package.head_workflow_id:
                default_name = workflow.name if not package.name else package.name
                self.package_store.update_package(
                    package_id,
                    user_id,
                    head_workflow_id=workflow_id,
                    name=default_name,
                )
        return self._require_package(user_id, package_id)

    def move_workflow(
        self, user_id: str, workflow_id: str, from_package_id: str, to_package_id: str
    ) -> WorkflowPackageRecord:
        self.package_store.remove_workflow_from_package(from_package_id, workflow_id)
        from_package = self._require_package(user_id, from_package_id)
        if from_package.head_workflow_id == workflow_id:
            remaining = [
                m.workflow_id
                for m in from_package.members
                if m.workflow_id != workflow_id
            ]
            self.package_store.update_package(
                from_package_id,
                user_id,
                head_workflow_id=remaining[0] if remaining else "",
            )
            if remaining:
                self.package_store.set_member_role(
                    from_package_id, remaining[0], "head"
                )
        target = self._require_package(user_id, to_package_id)
        role = "head" if not target.head_workflow_id else "dependency"
        self.package_store.add_workflow_to_package(
            to_package_id, workflow_id, role=role
        )
        if not target.head_workflow_id:
            workflow = self._require_workflow(user_id, workflow_id)
            self.package_store.update_package(
                to_package_id,
                user_id,
                head_workflow_id=workflow_id,
                name=target.name or workflow.name,
            )
        return self._require_package(user_id, to_package_id)

    def remove_workflow(
        self, user_id: str, package_id: str, workflow_id: str
    ) -> WorkflowPackageRecord:
        package = self._require_package(user_id, package_id)
        self.package_store.remove_workflow_from_package(package_id, workflow_id)
        if package.head_workflow_id == workflow_id:
            remaining = [
                m.workflow_id for m in package.members if m.workflow_id != workflow_id
            ]
            new_head = remaining[0] if remaining else ""
            self.package_store.update_package(
                package_id, user_id, head_workflow_id=new_head
            )
            if remaining:
                self.package_store.set_member_role(package_id, remaining[0], "head")
        return self._require_package(user_id, package_id)

    def set_head_workflow(
        self, user_id: str, package_id: str, workflow_id: str
    ) -> WorkflowPackageRecord:
        package = self._require_package(user_id, package_id)
        member_ids = {member.workflow_id for member in package.members}
        if workflow_id not in member_ids:
            raise ValueError("Workflow is not a package member")
        if package.head_workflow_id:
            self.package_store.set_member_role(
                package_id, package.head_workflow_id, "dependency"
            )
        self.package_store.set_member_role(package_id, workflow_id, "head")
        self.package_store.update_package(
            package_id, user_id, head_workflow_id=workflow_id
        )
        return self._require_package(user_id, package_id)

    def validate_package(self, user_id: str, package_id: str) -> List[PackageIssue]:
        package = self._require_package(user_id, package_id)
        issues: List[PackageIssue] = []
        if not package.members:
            issues.append(
                PackageIssue(code="empty_package", message="Package has no workflows")
            )
            return issues
        if not package.head_workflow_id:
            issues.append(
                PackageIssue(
                    code="missing_head", message="Package has no head workflow"
                )
            )
        for member in package.members:
            workflow = self._require_workflow(user_id, member.workflow_id)
            if workflow.is_draft:
                issues.append(
                    PackageIssue(
                        code="draft_workflow",
                        message=f"Workflow '{workflow.name}' is still a draft",
                        workflow_id=workflow.id,
                    )
                )
            if not workflow.is_validated:
                issues.append(
                    PackageIssue(
                        code="invalid_workflow",
                        message=f"Workflow '{workflow.name}' is not validated",
                        workflow_id=workflow.id,
                    )
                )
        return issues

    def publish_package(self, user_id: str, package_id: str) -> WorkflowPackageRecord:
        issues = self.validate_package(user_id, package_id)
        if issues:
            raise ValueError(issues[0].message)
        self.package_store.update_package(
            package_id,
            user_id,
            is_published=True,
            published_at=datetime.now(timezone.utc).isoformat(),
        )
        return self._require_package(user_id, package_id)

    def clone_package(
        self, source_package_id: str, target_user_id: str
    ) -> WorkflowPackageRecord:
        source_package, source_owner_id = self._require_any_package(source_package_id)
        cloned_package = self.package_store.create_package(target_user_id)
        id_map: Dict[str, str] = {}

        for member in source_package.members:
            source_workflow = self._require_workflow(
                source_owner_id, member.workflow_id
            )
            cloned_id = f"wf_{uuid4().hex}"
            id_map[source_workflow.id] = cloned_id
            self.workflow_store.create_workflow(
                workflow_id=cloned_id,
                user_id=target_user_id,
                name=source_workflow.name,
                description=source_workflow.description,
                domain=source_workflow.domain,
                tags=source_workflow.tags,
                nodes=source_workflow.nodes,
                edges=source_workflow.edges,
                inputs=source_workflow.inputs,
                outputs=source_workflow.outputs,
                tree=source_workflow.tree,
                doubts=source_workflow.doubts,
                is_validated=source_workflow.is_validated,
                output_type=source_workflow.output_type,
                is_draft=source_workflow.is_draft,
                is_published=False,
            )

        for member in source_package.members:
            cloned_id = id_map[member.workflow_id]
            cloned_workflow = self._require_workflow(target_user_id, cloned_id)
            rewritten_nodes: List[dict] = []
            rewritten_inputs: List[dict] = []
            for node in cloned_workflow.nodes:
                node_copy = dict(node)
                sub_id = node_copy.get("subworkflow_id")
                if isinstance(sub_id, str) and sub_id in id_map:
                    node_copy["subworkflow_id"] = id_map[sub_id]
                rewritten_nodes.append(node_copy)
            for variable in cloned_workflow.inputs:
                variable_copy = dict(variable)
                sub_id = variable_copy.get("subworkflow_id")
                if isinstance(sub_id, str) and sub_id in id_map:
                    variable_copy["subworkflow_id"] = id_map[sub_id]
                rewritten_inputs.append(variable_copy)
            self.workflow_store.update_workflow(
                workflow_id=cloned_id,
                user_id=target_user_id,
                nodes=rewritten_nodes,
                inputs=rewritten_inputs,
            )
            self.package_store.add_workflow_to_package(
                cloned_package.id,
                cloned_id,
                role=member.role,
            )

        if source_package.head_workflow_id:
            self.package_store.update_package(
                cloned_package.id,
                target_user_id,
                head_workflow_id=id_map[source_package.head_workflow_id],
            )
        return self._require_package(target_user_id, cloned_package.id)

    def autofetch_subflows_preview(
        self, user_id: str, package_id: str
    ) -> Dict[str, object]:
        package = self._require_package(user_id, package_id)
        if not package.head_workflow_id:
            raise ValueError("Package has no head workflow")

        additions: List[Dict[str, str]] = []
        conflicts: List[Dict[str, str]] = []
        visited: set[str] = set()
        member_ids = {member.workflow_id for member in package.members}
        stack = [package.head_workflow_id]

        while stack:
            workflow_id = stack.pop()
            if workflow_id in visited:
                continue
            visited.add(workflow_id)
            workflow = self._require_workflow(user_id, workflow_id)
            for node in workflow.nodes:
                if node.get("type") != "subprocess":
                    continue
                sub_id = node.get("subworkflow_id")
                if not isinstance(sub_id, str) or not sub_id:
                    continue
                if sub_id in member_ids:
                    stack.append(sub_id)
                    continue
                existing_package_id = self.package_store.get_workflow_package_id(sub_id)
                subflow = self.workflow_store.get_workflow(sub_id, user_id)
                if subflow is None:
                    continue
                if existing_package_id and existing_package_id != package_id:
                    conflicts.append(
                        {
                            "workflow_id": subflow.id,
                            "workflow_name": subflow.name,
                            "from_workflow_id": workflow.id,
                            "from_workflow_name": workflow.name,
                            "existing_package_id": existing_package_id,
                        }
                    )
                else:
                    additions.append(
                        {
                            "workflow_id": subflow.id,
                            "workflow_name": subflow.name,
                            "from_workflow_id": workflow.id,
                            "from_workflow_name": workflow.name,
                        }
                    )
                    stack.append(sub_id)
        return {"additions": additions, "conflicts": conflicts}

    def autofetch_subflows_apply(
        self,
        user_id: str,
        package_id: str,
        *,
        clone_conflict_workflow_ids: Optional[List[str]] = None,
    ) -> Tuple[WorkflowPackageRecord, Dict[str, object]]:
        preview = self.autofetch_subflows_preview(user_id, package_id)
        additions: Any = preview.get("additions", [])
        conflicts: Any = preview.get("conflicts", [])
        clone_ids = set(clone_conflict_workflow_ids or [])
        clone_map: Dict[str, str] = {}

        if not isinstance(additions, list) or not isinstance(conflicts, list):
            raise ValueError("Invalid autofetch preview")

        for addition in additions:
            self.add_workflow(user_id, package_id, addition["workflow_id"])

        for conflict in conflicts:
            conflict_id = conflict["workflow_id"]
            if conflict_id not in clone_ids:
                continue
            original = self._require_workflow(user_id, conflict_id)
            cloned_id = f"wf_{uuid4().hex}"
            self.workflow_store.create_workflow(
                workflow_id=cloned_id,
                user_id=user_id,
                name=original.name,
                description=original.description,
                domain=original.domain,
                tags=original.tags,
                nodes=original.nodes,
                edges=original.edges,
                inputs=original.inputs,
                outputs=original.outputs,
                tree=original.tree,
                doubts=original.doubts,
                is_validated=original.is_validated,
                output_type=original.output_type,
                is_draft=original.is_draft,
                is_published=False,
            )
            clone_map[conflict_id] = cloned_id
            self.add_workflow(user_id, package_id, cloned_id)

        if clone_map:
            package = self._require_package(user_id, package_id)
            for member in package.members:
                workflow = self._require_workflow(user_id, member.workflow_id)
                updated = False
                nodes = []
                variables = []
                for node in workflow.nodes:
                    node_copy = dict(node)
                    sub_id = node_copy.get("subworkflow_id")
                    if isinstance(sub_id, str) and sub_id in clone_map:
                        node_copy["subworkflow_id"] = clone_map[sub_id]
                        updated = True
                    nodes.append(node_copy)
                for variable in workflow.inputs:
                    variable_copy = dict(variable)
                    sub_id = variable_copy.get("subworkflow_id")
                    if isinstance(sub_id, str) and sub_id in clone_map:
                        variable_copy["subworkflow_id"] = clone_map[sub_id]
                        updated = True
                    variables.append(variable_copy)
                if updated:
                    self.workflow_store.update_workflow(
                        workflow_id=workflow.id,
                        user_id=user_id,
                        nodes=nodes,
                        inputs=variables,
                    )

        return self._require_package(user_id, package_id), {
            "preview": preview,
            "clone_map": clone_map,
        }

    def _require_package(self, user_id: str, package_id: str) -> WorkflowPackageRecord:
        package = self.package_store.get_package(package_id, user_id)
        if package is None:
            raise ValueError("Package not found")
        return package

    def _require_any_package(
        self, package_id: str
    ) -> tuple[WorkflowPackageRecord, str]:
        with self.package_store._conn() as conn:
            row = conn.execute(
                "SELECT user_id FROM workflow_packages WHERE id = ?",
                (package_id,),
            ).fetchone()
        if row is None:
            raise ValueError("Package not found")
        user_id = row["user_id"]
        package = self.package_store.get_package(package_id, user_id)
        if package is None:
            raise ValueError("Package not found")
        return package, user_id

    def _require_workflow(self, user_id: str, workflow_id: str) -> WorkflowRecord:
        workflow = self.workflow_store.get_workflow(workflow_id, user_id)
        if workflow is None:
            raise ValueError("Workflow not found")
        return workflow
