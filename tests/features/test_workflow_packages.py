from pathlib import Path

from src.backend.storage.workflows import WorkflowStore
from src.backend.workflow_packages import apply_package_report, build_package_report


def test_build_package_report_treats_other_package_members_as_external(tmp_path: Path):
    store = WorkflowStore(tmp_path / "workflows.sqlite")
    user_id = "user_1"

    store.create_workflow(
        workflow_id="wf_shared",
        user_id=user_id,
        name="Shared",
        description="",
        nodes=[],
        edges=[],
        inputs=[],
        outputs=[],
        tree={},
        doubts=[],
        is_draft=False,
        package_id="pkg_existing",
        package_name="Existing",
        package_role="dependency",
        package_head_workflow_id="wf_existing_head",
    )
    store.create_workflow(
        workflow_id="wf_root",
        user_id=user_id,
        name="Root",
        description="",
        nodes=[
            {
                "id": "sub",
                "type": "subprocess",
                "label": "Shared",
                "x": 0,
                "y": 0,
                "subworkflow_id": "wf_shared",
                "input_mapping": {},
                "output_variable": "result",
            }
        ],
        edges=[],
        inputs=[],
        outputs=[],
        tree={},
        doubts=[],
        is_draft=False,
    )

    report = build_package_report(store, user_id=user_id, head_workflow_id="wf_root")

    assert report.head_workflow_id == "wf_root"
    assert report.member_workflow_ids == ["wf_root"]
    assert report.external_dependency_ids == ["wf_shared"]


def test_apply_package_report_marks_head_and_dependencies(tmp_path: Path):
    store = WorkflowStore(tmp_path / "workflows.sqlite")
    user_id = "user_1"

    for workflow_id in ("wf_root", "wf_child"):
        store.create_workflow(
            workflow_id=workflow_id,
            user_id=user_id,
            name=workflow_id,
            description="",
            nodes=[],
            edges=[],
            inputs=[],
            outputs=[],
            tree={},
            doubts=[],
            is_draft=False,
        )

    report = build_package_report(
        store,
        user_id=user_id,
        head_workflow_id="wf_root",
        package_id="pkg_1",
        package_name="Pkg 1",
    )
    report = report.__class__(
        package_id=report.package_id,
        package_name=report.package_name,
        head_workflow_id=report.head_workflow_id,
        member_workflow_ids=["wf_root", "wf_child"],
        external_dependency_ids=[],
        missing_dependency_ids=[],
    )

    apply_package_report(store, user_id=user_id, report=report)

    head = store.get_workflow("wf_root", user_id)
    child = store.get_workflow("wf_child", user_id)
    assert head is not None and child is not None
    assert head.package_role == "head"
    assert child.package_role == "dependency"
    assert child.package_head_workflow_id == "wf_root"
