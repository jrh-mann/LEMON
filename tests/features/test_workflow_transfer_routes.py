import io
import json
import zipfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.api.routes import workflow_routes
from src.backend.api.routes.package_routes import register_package_routes
from src.backend.api.routes.workflow_routes import register_workflow_routes
from src.backend.storage.auth import AuthUser
from src.backend.storage.packages import PackageStore
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
    register_package_routes(app, workflow_store=workflow_store)
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
        package_id="pkg_root",
        package_name="Root Package",
        package_role="dependency",
        package_head_workflow_id="wf_root",
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
        package_id="pkg_root",
        package_name="Root Package",
        package_role="head",
        package_head_workflow_id="wf_root",
    )

    export_resp = client.get("/api/workflows/wf_root/export-bundle")
    assert export_resp.status_code == 200

    with zipfile.ZipFile(io.BytesIO(export_resp.content), "r") as zf:
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["entry_workflow_id"] == "wf_root"
        assert set(manifest["workflow_ids"]) == {"wf_root", "wf_child"}
        assert manifest["package"]["name"] == "Root Package"
        assert manifest["package"]["head_workflow_id"] == "wf_root"
        exported_root = json.loads(zf.read("workflows/wf_root.json"))
        assert "validation_score" not in exported_root["metadata"]
        assert "validation_count" not in exported_root["metadata"]
        assert exported_root["package"]["role"] == "head"
    assert export_resp.headers.get("X-LEMON-Export-Warnings") == "[]"

    import_resp = client.post(
        "/api/workflows/import-bundle",
        files={"file": ("bundle.zip", export_resp.content, "application/zip")},
    )
    assert import_resp.status_code == 201
    body = import_resp.json()
    assert body["imported_count"] == 2
    assert body["imported_kind"] == "package_bundle"
    assert body["package_id"].startswith("pkg_")

    imported_root = workflow_store.get_workflow(body["workflow_id"], user.id)
    assert imported_root is not None
    assert imported_root.package_name == "Root Package"
    assert imported_root.package_role == "head"
    assert imported_root.package_id == body["package_id"]
    subprocess_node = next(
        node for node in imported_root.nodes if node["type"] == "subprocess"
    )
    imported_child_id = subprocess_node["subworkflow_id"]
    assert imported_child_id != "wf_child"
    imported_child = workflow_store.get_workflow(imported_child_id, user.id)
    assert imported_child is not None
    assert imported_child.package_name == "Root Package"
    assert imported_child.package_head_workflow_id == imported_root.id

    package_store = PackageStore(workflow_store.db_path)
    imported_package = package_store.get_package(body["package_id"], user.id)
    assert imported_package is not None
    assert imported_package.head_workflow_id == imported_root.id
    assert {member.workflow_id for member in imported_package.members} == {
        imported_root.id,
        imported_child_id,
    }


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
    assert stored.is_validated is True


def test_import_package_bundle_creates_real_package(tmp_path: Path):
    client, workflow_store, user = _client(tmp_path)

    workflow_store.create_workflow(
        workflow_id="wf_head",
        user_id=user.id,
        name="Head",
        description="head desc",
        domain=None,
        tags=[],
        nodes=[
            {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
            {"id": "end", "type": "end", "label": "Done", "x": 100, "y": 0},
        ],
        edges=[{"from": "start", "to": "end"}],
        inputs=[],
        outputs=[],
        tree={},
        doubts=[],
        output_type="string",
        is_draft=False,
        is_validated=True,
    )
    workflow_store.create_workflow(
        workflow_id="wf_dependency",
        user_id=user.id,
        name="Dependency",
        description="dep desc",
        domain=None,
        tags=[],
        nodes=[
            {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
            {"id": "end", "type": "end", "label": "Done", "x": 100, "y": 0},
        ],
        edges=[{"from": "start", "to": "end"}],
        inputs=[],
        outputs=[],
        tree={},
        doubts=[],
        output_type="string",
        is_draft=False,
        is_validated=True,
    )

    package_id = client.post(
        "/api/packages",
        json={"name": "Pack", "description": "desc"},
    ).json()["id"]
    client.post(f"/api/packages/{package_id}/members", json={"workflow_id": "wf_head"})
    client.post(
        f"/api/packages/{package_id}/members",
        json={"workflow_id": "wf_dependency"},
    )

    export_resp = client.get(f"/api/packages/{package_id}/export-bundle")
    assert export_resp.status_code == 200

    import_resp = client.post(
        "/api/workflows/import-bundle",
        files={
            "file": (
                "package.zip",
                export_resp.json()["content"].encode("latin1"),
                "application/zip",
            )
        },
    )
    assert import_resp.status_code == 201
    body = import_resp.json()
    assert body["imported_kind"] == "package_bundle"

    package_store = PackageStore(workflow_store.db_path)
    imported_package = package_store.get_package(body["package_id"], user.id)
    assert imported_package is not None
    assert imported_package.name == "Pack"
    assert imported_package.description == "desc"
    assert len(imported_package.members) == 2
    assert imported_package.head_workflow_id == body["workflow_id"]


def test_invalid_import_returns_validation_errors_without_force_import(tmp_path: Path):
    client, _, _ = _client(tmp_path)
    payload = {
        "id": "wf_invalid",
        "metadata": {"name": "Invalid"},
        "flowchart": {
            "nodes": [
                {"id": "start1", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "start2", "type": "start", "label": "Input", "x": 10, "y": 0},
            ],
            "edges": [],
        },
        "variables": [],
        "outputs": [],
        "output_type": "string",
    }

    response = client.post("/api/workflows/import", json=payload)

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "Workflow validation failed"
    assert body["validation_errors"]


def test_invalid_import_anyway_persists_unvalidated(tmp_path: Path):
    client, workflow_store, user = _client(tmp_path)
    payload = {
        "id": "wf_invalid",
        "metadata": {"name": "Invalid"},
        "flowchart": {
            "nodes": [
                {"id": "start1", "type": "start", "label": "Start", "x": 0, "y": 0},
                {"id": "start2", "type": "start", "label": "Input", "x": 10, "y": 0},
            ],
            "edges": [],
        },
        "variables": [],
        "outputs": [],
        "output_type": "string",
    }

    response = client.post("/api/workflows/import?force_import=true", json=payload)

    assert response.status_code == 201
    workflow_id = response.json()["workflow_id"]
    stored = workflow_store.get_workflow(workflow_id, user.id)
    assert stored is not None
    assert stored.is_validated is False


def test_bundle_export_reports_recursive_subflow_warning(tmp_path: Path):
    client, workflow_store, user = _client(tmp_path)

    workflow_store.create_workflow(
        workflow_id="wf_a",
        user_id=user.id,
        name="A",
        description="",
        domain=None,
        tags=[],
        nodes=[
            {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
            {
                "id": "sub",
                "type": "subprocess",
                "label": "B",
                "x": 0,
                "y": 100,
                "subworkflow_id": "wf_b",
                "input_mapping": {},
                "output_variable": "out",
            },
            {
                "id": "end",
                "type": "end",
                "label": "Done",
                "x": 0,
                "y": 200,
                "output_variable": "out",
                "output_type": "string",
            },
        ],
        edges=[{"from": "start", "to": "sub"}, {"from": "sub", "to": "end"}],
        inputs=[],
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
    workflow_store.create_workflow(
        workflow_id="wf_b",
        user_id=user.id,
        name="B",
        description="",
        domain=None,
        tags=[],
        nodes=[
            {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
            {
                "id": "sub",
                "type": "subprocess",
                "label": "A",
                "x": 0,
                "y": 100,
                "subworkflow_id": "wf_a",
                "input_mapping": {},
                "output_variable": "out",
            },
            {
                "id": "end",
                "type": "end",
                "label": "Done",
                "x": 0,
                "y": 200,
                "output_variable": "out",
                "output_type": "string",
            },
        ],
        edges=[{"from": "start", "to": "sub"}, {"from": "sub", "to": "end"}],
        inputs=[],
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

    export_resp = client.get("/api/workflows/wf_a/export-bundle")

    assert export_resp.status_code == 200
    warnings = json.loads(export_resp.headers["X-LEMON-Export-Warnings"])
    assert any("Recursive subflow cycle detected" in warning for warning in warnings)


def test_bundle_export_allows_missing_subflow_with_warning(tmp_path: Path):
    client, workflow_store, user = _client(tmp_path)

    workflow_store.create_workflow(
        workflow_id="wf_root_missing_child",
        user_id=user.id,
        name="Root Missing Child",
        description="",
        domain=None,
        tags=[],
        nodes=[
            {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
            {
                "id": "sub",
                "type": "subprocess",
                "label": "Missing",
                "x": 0,
                "y": 100,
                "subworkflow_id": "wf_missing",
                "input_mapping": {},
                "output_variable": "out",
            },
            {
                "id": "end",
                "type": "end",
                "label": "Done",
                "x": 0,
                "y": 200,
                "output_variable": "out",
                "output_type": "string",
            },
        ],
        edges=[{"from": "start", "to": "sub"}, {"from": "sub", "to": "end"}],
        inputs=[],
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

    export_resp = client.get("/api/workflows/wf_root_missing_child/export-bundle")

    assert export_resp.status_code == 200
    warnings = json.loads(export_resp.headers["X-LEMON-Export-Warnings"])
    assert any(
        "could not be fetched and was omitted from the bundle" in warning
        for warning in warnings
    )

    with zipfile.ZipFile(io.BytesIO(export_resp.content), "r") as zf:
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["workflow_ids"] == ["wf_root_missing_child"]
        assert manifest["missing_workflow_ids"] == ["wf_missing"]
        assert "workflows/wf_root_missing_child.json" in zf.namelist()
        assert "workflows/wf_missing.json" in zf.namelist()
        placeholder = json.loads(zf.read("workflows/wf_missing.json"))
        assert placeholder["id"] == "wf_missing"
        assert placeholder["metadata"]["is_placeholder"] is True
        assert placeholder["metadata"]["placeholder_reason"] == "missing_subworkflow"


def test_invalid_bundle_import_requires_force_import(tmp_path: Path):
    client, workflow_store, user = _client(tmp_path)

    workflow_store.create_workflow(
        workflow_id="wf_invalid_bundle_source",
        user_id=user.id,
        name="Invalid Bundle Source",
        description="",
        domain=None,
        tags=[],
        nodes=[
            {"id": "start1", "type": "start", "label": "Start", "x": 0, "y": 0},
            {"id": "start2", "type": "start", "label": "Input", "x": 10, "y": 0},
        ],
        edges=[],
        inputs=[],
        outputs=[],
        tree={"start": {"id": "start1", "children": []}},
        doubts=[],
        output_type="string",
        is_draft=False,
        is_validated=False,
    )

    export_resp = client.get("/api/workflows/wf_invalid_bundle_source/export-bundle")
    assert export_resp.status_code == 200

    import_resp = client.post(
        "/api/workflows/import-bundle",
        files={"file": ("bundle.zip", export_resp.content, "application/zip")},
    )
    assert import_resp.status_code == 400
    assert import_resp.json()["error"] == "Workflow validation failed"

    forced_resp = client.post(
        "/api/workflows/import-bundle?force_import=true",
        files={"file": ("bundle.zip", export_resp.content, "application/zip")},
    )
    assert forced_resp.status_code == 201


def test_placeholder_workflow_import_is_rejected(tmp_path: Path):
    client, _, _ = _client(tmp_path)
    payload = {
        "id": "wf_missing",
        "metadata": {
            "name": "Missing Subworkflow",
            "description": "Placeholder exported because the referenced subworkflow could not be fetched.",
            "tags": [],
            "is_placeholder": True,
            "placeholder_reason": "missing_subworkflow",
        },
        "flowchart": {"nodes": [], "edges": []},
        "variables": [],
        "outputs": [],
        "output_type": "string",
    }

    response = client.post("/api/workflows/import", json=payload)

    assert response.status_code == 400
    assert (
        response.json()["error"]
        == "Cannot import placeholder workflow for missing subflow"
    )
