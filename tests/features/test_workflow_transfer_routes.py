import io
import json
import zipfile
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


def test_export_bundle_and_import_bundle(tmp_path: Path):
    client, workflow_store, user = _client(tmp_path)

    child_id = "wf_child"
    workflow_store.create_workflow(
        workflow_id=child_id,
        user_id=user.id,
        name="Child",
        description="",
        domain=None,
        tags=[],
        nodes=[
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
        edges=[{"from": "start", "to": "end"}],
        inputs=[],
        outputs=[{"name": "result", "type": "string"}],
        tree={"start": {"id": "start", "children": [{"id": "end", "children": []}]}},
        doubts=[],
        output_type="string",
        is_draft=False,
    )
    workflow_store.create_workflow(
        workflow_id="wf_root",
        user_id=user.id,
        name="Root",
        description="",
        domain=None,
        tags=[],
        nodes=[
            {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
            {
                "id": "sub",
                "type": "subprocess",
                "label": "Child",
                "x": 0,
                "y": 100,
                "subworkflow_id": child_id,
                "input_mapping": {},
                "output_variable": "child_result",
            },
            {
                "id": "end",
                "type": "end",
                "label": "Done",
                "x": 0,
                "y": 200,
                "output_type": "string",
                "output_template": "{child_result}",
            },
        ],
        edges=[{"from": "start", "to": "sub"}, {"from": "sub", "to": "end"}],
        inputs=[
            {
                "id": "var_sub_child_result_string",
                "name": "child_result",
                "type": "string",
                "source": "subprocess",
                "source_node_id": "sub",
                "subworkflow_id": child_id,
            }
        ],
        outputs=[{"name": "result", "type": "string"}],
        tree={
            "start": {
                "id": "start",
                "children": [
                    {"id": "sub", "children": [{"id": "end", "children": []}]}
                ],
            }
        },
        doubts=[],
        output_type="string",
        is_draft=False,
    )

    export_resp = client.get("/api/workflows/wf_root/export-bundle")
    assert export_resp.status_code == 200

    with zipfile.ZipFile(io.BytesIO(export_resp.content), "r") as zf:
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["entry_workflow_id"] == "wf_root"
        assert set(manifest["workflow_ids"]) == {"wf_root", "wf_child"}
        exported_root = json.loads(zf.read("workflows/wf_root.json"))
        assert "validation_score" not in exported_root["metadata"]
        assert "validation_count" not in exported_root["metadata"]

    import_resp = client.post(
        "/api/workflows/import-bundle",
        files={"file": ("bundle.zip", export_resp.content, "application/zip")},
    )
    assert import_resp.status_code == 201
    body = import_resp.json()
    assert body["imported_count"] == 2

    imported_root = workflow_store.get_workflow(body["workflow_id"], user.id)
    assert imported_root is not None
    subprocess_node = next(
        node for node in imported_root.nodes if node["type"] == "subprocess"
    )
    imported_child_id = subprocess_node["subworkflow_id"]
    assert imported_child_id != "wf_child"
    assert workflow_store.get_workflow(imported_child_id, user.id) is not None


def test_import_single_workflow_persists_immediately(tmp_path: Path):
    client, workflow_store, user = _client(tmp_path)
    payload = {
        "id": "wf_source",
        "metadata": {"name": "Imported"},
        "flowchart": {
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
        },
        "variables": [],
        "outputs": [{"name": "result", "type": "string"}],
        "output_type": "string",
    }

    resp = client.post("/api/workflows/import", json=payload)
    assert resp.status_code == 201
    workflow_id = resp.json()["workflow_id"]
    stored = workflow_store.get_workflow(workflow_id, user.id)
    assert stored is not None
    assert stored.name == "Imported"
