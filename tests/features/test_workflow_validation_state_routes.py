from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.api.routes import workflow_routes
from src.backend.api.routes.workflow_routes import register_workflow_routes
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


def _client(tmp_path: Path) -> tuple[TestClient, WorkflowStore, AuthUser]:
    app = FastAPI()
    workflow_store = WorkflowStore(tmp_path / "workflows.sqlite")
    register_workflow_routes(app, repo_root=Path.cwd(), workflow_store=workflow_store)
    user = _user()
    app.dependency_overrides[workflow_routes.require_auth] = lambda: user
    return TestClient(app), workflow_store, user


def _valid_payload() -> dict:
    return {
        "name": "Valid Workflow",
        "description": "",
        "nodes": [
            {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
            {
                "id": "end",
                "type": "end",
                "label": "Done",
                "x": 0,
                "y": 100,
                "output_type": "string",
                "output_value": "ok",
            },
        ],
        "edges": [{"from": "start", "to": "end"}],
        "variables": [],
        "outputs": [{"name": "result", "type": "string"}],
        "output_type": "string",
    }


def _invalid_payload() -> dict:
    return {
        "name": "Invalid Workflow",
        "description": "",
        "nodes": [
            {"id": "start1", "type": "start", "label": "Start", "x": 0, "y": 0},
            {"id": "start2", "type": "start", "label": "Input", "x": 50, "y": 0},
            {
                "id": "end",
                "type": "end",
                "label": "Done",
                "x": 0,
                "y": 100,
                "output_type": "string",
                "output_value": "ok",
            },
        ],
        "edges": [{"from": "start1", "to": "end"}],
        "variables": [],
        "outputs": [{"name": "result", "type": "string"}],
        "output_type": "string",
    }


def test_valid_save_marks_workflow_validated(tmp_path: Path):
    client, workflow_store, user = _client(tmp_path)

    response = client.post(
        "/api/workflows", json={**_valid_payload(), "id": "wf_valid"}
    )

    assert response.status_code == 201
    saved = workflow_store.get_workflow("wf_valid", user.id)
    assert saved is not None
    assert saved.is_validated is True
    detail = client.get("/api/workflows/wf_valid")
    assert detail.status_code == 200
    metadata = detail.json()["metadata"]
    assert "validation_score" not in metadata
    assert "validation_count" not in metadata


def test_invalid_save_rejected_without_force_save(tmp_path: Path):
    client, _, _ = _client(tmp_path)

    response = client.post(
        "/api/workflows", json={**_invalid_payload(), "id": "wf_invalid"}
    )

    assert response.status_code == 400
    assert response.json()["error"] == "Workflow validation failed"


def test_invalid_save_anyway_persists_with_unvalidated_flag(tmp_path: Path):
    client, workflow_store, user = _client(tmp_path)

    response = client.post(
        "/api/workflows",
        json={**_invalid_payload(), "id": "wf_force", "force_save": True},
    )

    assert response.status_code == 201
    saved = workflow_store.get_workflow("wf_force", user.id)
    assert saved is not None
    assert saved.is_validated is False


def test_patch_invalidates_previous_validation_state(tmp_path: Path):
    client, workflow_store, user = _client(tmp_path)
    workflow_store.create_workflow(
        workflow_id="wf_patch",
        user_id=user.id,
        name="Patch Target",
        description="",
        domain=None,
        tags=[],
        nodes=_valid_payload()["nodes"],
        edges=_valid_payload()["edges"],
        inputs=[],
        outputs=[{"name": "result", "type": "string"}],
        tree={"start": {"id": "start", "children": [{"id": "end", "children": []}]}},
        doubts=[],
        is_validated=True,
        output_type="string",
        is_draft=False,
    )

    patch_response = client.patch(
        "/api/workflows/wf_patch",
        json={
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                {
                    "id": "end",
                    "type": "end",
                    "label": "Done",
                    "x": 0,
                    "y": 120,
                    "output_type": "string",
                    "output_value": "changed",
                },
            ]
        },
    )

    assert patch_response.status_code == 200
    patched = workflow_store.get_workflow("wf_patch", user.id)
    assert patched is not None
    assert patched.is_validated is False
