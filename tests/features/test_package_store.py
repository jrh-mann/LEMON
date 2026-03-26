from pathlib import Path

from src.backend.storage.packages import PackageStore
from src.backend.storage.workflows import WorkflowStore
from src.backend.workflow_package_service import WorkflowPackageService


def test_create_empty_package(tmp_path: Path):
    workflow_store = WorkflowStore(tmp_path / "workflows.sqlite")
    service = WorkflowPackageService(workflow_store)

    package = service.create_package("user_1")

    assert package.name == ""
    assert package.head_workflow_id is None
    assert package.members == []


def test_first_added_workflow_becomes_head(tmp_path: Path):
    workflow_store = WorkflowStore(tmp_path / "workflows.sqlite")
    service = WorkflowPackageService(workflow_store)
    workflow_store.create_workflow(
        "wf_1",
        "user_1",
        "Workflow One",
        "",
        nodes=[],
        edges=[],
        inputs=[],
        outputs=[],
        tree={},
        doubts=[],
        is_draft=False,
    )
    package = service.create_package("user_1")

    updated = service.add_workflow("user_1", package.id, "wf_1")

    assert updated.head_workflow_id == "wf_1"
    assert updated.name == "Workflow One"


def test_move_workflow_between_packages(tmp_path: Path):
    workflow_store = WorkflowStore(tmp_path / "workflows.sqlite")
    service = WorkflowPackageService(workflow_store)
    workflow_store.create_workflow(
        "wf_1",
        "user_1",
        "Workflow One",
        "",
        nodes=[],
        edges=[],
        inputs=[],
        outputs=[],
        tree={},
        doubts=[],
        is_draft=False,
    )
    package_a = service.create_package("user_1", name="A")
    package_b = service.create_package("user_1", name="B")
    service.add_workflow("user_1", package_a.id, "wf_1")

    moved = service.add_workflow("user_1", package_b.id, "wf_1")

    assert moved.id == package_b.id
    assert moved.head_workflow_id == "wf_1"
