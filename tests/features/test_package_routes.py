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


def test_create_add_head_and_publish_package(tmp_path: Path):
    client, workflow_store, user = _client(tmp_path)
    workflow_store.create_workflow(
        "wf_1",
        user.id,
        "WF 1",
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

    created = client.post("/api/packages", json={"name": ""})
    assert created.status_code == 201
    package_id = created.json()["id"]

    added = client.post(
        f"/api/packages/{package_id}/members", json={"workflow_id": "wf_1"}
    )
    assert added.status_code == 200
    assert added.json()["head_workflow_id"] == "wf_1"

    published = client.post(f"/api/packages/{package_id}/publish")
    assert published.status_code == 200
    assert published.json()["is_published"] is True


def test_package_autofetch_clones_conflicts(tmp_path: Path):
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
                "id": "sub",
                "type": "subprocess",
                "label": "Shared",
                "x": 0,
                "y": 0,
                "subworkflow_id": "wf_shared",
                "input_mapping": {},
                "output_variable": "out",
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

    pkg_a = client.post("/api/packages", json={}).json()["id"]
    client.post(f"/api/packages/{pkg_a}/members", json={"workflow_id": "wf_shared"})
    pkg_b = client.post("/api/packages", json={}).json()["id"]
    client.post(f"/api/packages/{pkg_b}/members", json={"workflow_id": "wf_root"})

    preview = client.post(f"/api/packages/{pkg_b}/autofetch-subflows/preview")
    assert preview.status_code == 200
    assert len(preview.json()["conflicts"]) == 1

    applied = client.post(
        f"/api/packages/{pkg_b}/autofetch-subflows/apply",
        json={"clone_conflict_workflow_ids": ["wf_shared"]},
    )
    assert applied.status_code == 200
    assert applied.json()["workflow_count"] == 2


def test_export_package_bundle(tmp_path: Path):
    client, workflow_store, user = _client(tmp_path)
    workflow_store.create_workflow(
        "wf_1",
        user.id,
        "WF 1",
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
    created = client.post("/api/packages", json={})
    package_id = created.json()["id"]
    client.post(f"/api/packages/{package_id}/members", json={"workflow_id": "wf_1"})

    exported = client.get(f"/api/packages/{package_id}/export-bundle")
    assert exported.status_code == 200
    body = exported.json()
    assert body["warnings"] == []
    assert body["content"]
