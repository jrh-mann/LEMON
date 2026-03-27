from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.api.routes import workflow_routes
from src.backend.api.routes.package_routes import register_package_routes
from src.backend.storage.auth import AuthUser
from src.backend.storage.workflows import WorkflowStore


def _user() -> AuthUser:
    return AuthUser(
        id="user_1",
        email="test@example.com",
        name="Test User",
        password_hash="hash",
        created_at="2026-01-01T00:00:00Z",
        last_login_at=None,
    )


def _client(tmp_path: Path):
    app = FastAPI()
    workflow_store = WorkflowStore(tmp_path / "workflows.sqlite")
    register_package_routes(app, workflow_store=workflow_store)
    user = _user()
    app.dependency_overrides[workflow_routes.require_auth] = lambda: user
    return TestClient(app), workflow_store, user


def test_package_autofetch_preview_deduplicates_repeated_subflow_references(
    tmp_path: Path,
):
    client, workflow_store, user = _client(tmp_path)
    workflow_store.create_workflow(
        "wf_shared",
        user.id,
        "Shared",
        "desc",
        nodes=[],
        edges=[],
        inputs=[],
        outputs=[],
        tree={},
        doubts=[],
        is_draft=False,
        is_validated=True,
    )
    workflow_store.create_workflow(
        "wf_root",
        user.id,
        "Root",
        "desc",
        nodes=[
            {
                "id": "sub_1",
                "type": "subprocess",
                "label": "Shared",
                "x": 0,
                "y": 0,
                "subworkflow_id": "wf_shared",
                "input_mapping": {},
                "output_variable": "out_1",
            },
            {
                "id": "sub_2",
                "type": "subprocess",
                "label": "Shared Again",
                "x": 120,
                "y": 0,
                "subworkflow_id": "wf_shared",
                "input_mapping": {},
                "output_variable": "out_2",
            },
        ],
        edges=[],
        inputs=[],
        outputs=[],
        tree={},
        doubts=[],
        is_draft=False,
        is_validated=True,
    )

    package_id = client.post("/api/packages", json={}).json()["id"]
    client.post(f"/api/packages/{package_id}/members", json={"workflow_id": "wf_root"})

    preview = client.post(f"/api/packages/{package_id}/autofetch-subflows/preview")
    assert preview.status_code == 200
    body = preview.json()
    assert [entry["workflow_id"] for entry in body["additions"]] == ["wf_shared"]
    assert body["conflicts"] == []


def test_package_autofetch_recurses_through_conflicts(tmp_path: Path):
    client, workflow_store, user = _client(tmp_path)
    workflow_store.create_workflow(
        "wf_leaf",
        user.id,
        "Leaf",
        "desc",
        nodes=[],
        edges=[],
        inputs=[],
        outputs=[],
        tree={},
        doubts=[],
        is_draft=False,
        is_validated=True,
    )
    workflow_store.create_workflow(
        "wf_conflict",
        user.id,
        "Conflict",
        "desc",
        nodes=[
            {
                "id": "sub_leaf",
                "type": "subprocess",
                "label": "Leaf",
                "x": 0,
                "y": 0,
                "subworkflow_id": "wf_leaf",
                "input_mapping": {},
                "output_variable": "leaf_out",
            }
        ],
        edges=[],
        inputs=[],
        outputs=[],
        tree={},
        doubts=[],
        is_draft=False,
        is_validated=True,
    )
    workflow_store.create_workflow(
        "wf_root",
        user.id,
        "Root",
        "desc",
        nodes=[
            {
                "id": "sub_conflict",
                "type": "subprocess",
                "label": "Conflict",
                "x": 0,
                "y": 0,
                "subworkflow_id": "wf_conflict",
                "input_mapping": {},
                "output_variable": "conflict_out",
            }
        ],
        edges=[],
        inputs=[],
        outputs=[],
        tree={},
        doubts=[],
        is_draft=False,
        is_validated=True,
    )

    pkg_conflict = client.post("/api/packages", json={}).json()["id"]
    client.post(
        f"/api/packages/{pkg_conflict}/members", json={"workflow_id": "wf_conflict"}
    )

    pkg_target = client.post("/api/packages", json={}).json()["id"]
    client.post(f"/api/packages/{pkg_target}/members", json={"workflow_id": "wf_root"})

    preview = client.post(f"/api/packages/{pkg_target}/autofetch-subflows/preview")
    assert preview.status_code == 200
    preview_body = preview.json()
    assert [entry["workflow_id"] for entry in preview_body["conflicts"]] == [
        "wf_conflict"
    ]
    assert [entry["workflow_id"] for entry in preview_body["additions"]] == ["wf_leaf"]

    applied = client.post(
        f"/api/packages/{pkg_target}/autofetch-subflows/apply",
        json={"clone_conflict_workflow_ids": ["wf_conflict"]},
    )
    assert applied.status_code == 200
    body = applied.json()

    clone_map = body["autofetch"]["clone_map"]
    assert "wf_conflict" in clone_map
    cloned_conflict_id = clone_map["wf_conflict"]

    member_ids = {entry["id"] for entry in body["workflows"]}
    assert member_ids == {"wf_root", "wf_leaf", cloned_conflict_id}

    root = workflow_store.get_workflow("wf_root", user.id)
    assert root is not None
    root_subprocess = next(node for node in root.nodes if node["type"] == "subprocess")
    assert root_subprocess["subworkflow_id"] == cloned_conflict_id

    cloned_conflict = workflow_store.get_workflow(cloned_conflict_id, user.id)
    assert cloned_conflict is not None
    cloned_subprocess = next(
        node for node in cloned_conflict.nodes if node["type"] == "subprocess"
    )
    assert cloned_subprocess["subworkflow_id"] == "wf_leaf"
