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


def test_compile_package_python_emits_unreferenced_member_functions(tmp_path: Path):
    client, workflow_store, user = _client(tmp_path)
    workflow_store.create_workflow(
        "wf_head",
        user.id,
        "Head",
        "desc",
        nodes=[
            {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
            {"id": "end", "type": "end", "label": "Done", "x": 120, "y": 0},
        ],
        edges=[{"id": "e1", "from": "start", "to": "end", "label": ""}],
        inputs=[],
        outputs=[],
        tree={},
        doubts=[],
        is_draft=False,
        is_validated=True,
    )
    workflow_store.create_workflow(
        "wf_dependency",
        user.id,
        "Dependency",
        "desc",
        nodes=[
            {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
            {"id": "end", "type": "end", "label": "Done", "x": 120, "y": 0},
        ],
        edges=[{"id": "e1", "from": "start", "to": "end", "label": ""}],
        inputs=[],
        outputs=[],
        tree={},
        doubts=[],
        is_draft=False,
        is_validated=True,
    )

    package_id = client.post("/api/packages", json={"name": "Package"}).json()["id"]
    client.post(f"/api/packages/{package_id}/members", json={"workflow_id": "wf_head"})
    client.post(
        f"/api/packages/{package_id}/members",
        json={"workflow_id": "wf_dependency"},
    )

    compiled = client.post(f"/api/packages/{package_id}/compile-python", json={})
    assert compiled.status_code == 200
    body = compiled.json()
    assert body["success"] is True
    assert "def package(" in body["code"].lower()
    assert "def subflow_wf_dependency" in body["code"]


def test_compile_package_python_requires_confirmation_for_external_subflow(
    tmp_path: Path,
):
    client, workflow_store, user = _client(tmp_path)
    workflow_store.create_workflow(
        "wf_external",
        user.id,
        "External",
        "desc",
        nodes=[
            {"id": "ext_start", "type": "start", "label": "Start", "x": 0, "y": 0},
            {"id": "ext_end", "type": "end", "label": "End", "x": 120, "y": 0},
        ],
        edges=[{"id": "ext_e1", "from": "ext_start", "to": "ext_end", "label": ""}],
        inputs=[],
        outputs=[],
        tree={},
        doubts=[],
        is_draft=False,
        is_validated=True,
    )
    workflow_store.create_workflow(
        "wf_head",
        user.id,
        "Head",
        "desc",
        nodes=[
            {"id": "n1", "type": "start", "label": "Start", "x": 0, "y": 0},
            {
                "id": "n2",
                "type": "subprocess",
                "label": "External",
                "x": 120,
                "y": 0,
                "subworkflow_id": "wf_external",
                "input_mapping": {},
                "output_variable": "ext_result",
            },
            {"id": "n3", "type": "end", "label": "End", "x": 240, "y": 0},
        ],
        edges=[
            {"id": "e1", "from": "n1", "to": "n2", "label": ""},
            {"id": "e2", "from": "n2", "to": "n3", "label": ""},
        ],
        inputs=[],
        outputs=[],
        tree={},
        doubts=[],
        is_draft=False,
        is_validated=True,
    )

    package_id = client.post("/api/packages", json={}).json()["id"]
    client.post(f"/api/packages/{package_id}/members", json={"workflow_id": "wf_head"})

    compiled = client.post(f"/api/packages/{package_id}/compile-python", json={})
    assert compiled.status_code == 200
    body = compiled.json()
    assert body["success"] is False
    assert body["requires_confirmation"] is True
    assert body["external_subflow_ids"] == ["wf_external"]


def test_compile_package_python_includes_external_subflow_when_confirmed(
    tmp_path: Path,
):
    client, workflow_store, user = _client(tmp_path)
    workflow_store.create_workflow(
        "wf_external",
        user.id,
        "External",
        "desc",
        nodes=[
            {"id": "ext_start", "type": "start", "label": "Start", "x": 0, "y": 0},
            {"id": "ext_end", "type": "end", "label": "End", "x": 120, "y": 0},
        ],
        edges=[{"id": "ext_e1", "from": "ext_start", "to": "ext_end", "label": ""}],
        inputs=[],
        outputs=[],
        tree={},
        doubts=[],
        is_draft=False,
        is_validated=True,
    )
    workflow_store.create_workflow(
        "wf_head",
        user.id,
        "Head",
        "desc",
        nodes=[
            {"id": "n1", "type": "start", "label": "Start", "x": 0, "y": 0},
            {
                "id": "n2",
                "type": "subprocess",
                "label": "External",
                "x": 120,
                "y": 0,
                "subworkflow_id": "wf_external",
                "input_mapping": {},
                "output_variable": "ext_result",
            },
            {"id": "n3", "type": "end", "label": "End", "x": 240, "y": 0},
        ],
        edges=[
            {"id": "e1", "from": "n1", "to": "n2", "label": ""},
            {"id": "e2", "from": "n2", "to": "n3", "label": ""},
        ],
        inputs=[],
        outputs=[],
        tree={},
        doubts=[],
        is_draft=False,
        is_validated=True,
    )

    package_id = client.post("/api/packages", json={}).json()["id"]
    client.post(f"/api/packages/{package_id}/members", json={"workflow_id": "wf_head"})

    compiled = client.post(
        f"/api/packages/{package_id}/compile-python",
        json={"include_external_subflows": True},
    )
    assert compiled.status_code == 200
    body = compiled.json()
    assert body["success"] is True
    assert "def subflow_wf_external" in body["code"]
    assert any("outside package membership" in warning for warning in body["warnings"])


def test_clone_package_creates_independent_copy(tmp_path: Path):
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
    package_id = client.post("/api/packages", json={}).json()["id"]
    client.post(f"/api/packages/{package_id}/members", json={"workflow_id": "wf_1"})
    client.post(f"/api/packages/{package_id}/publish")

    cloned = client.post(f"/api/packages/{package_id}/clone")
    assert cloned.status_code == 201
    assert cloned.json()["id"] != package_id
    assert cloned.json()["workflows"][0]["id"] != "wf_1"


def test_delete_package_keeps_workflows(tmp_path: Path):
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
    package_id = client.post("/api/packages", json={}).json()["id"]
    client.post(f"/api/packages/{package_id}/members", json={"workflow_id": "wf_1"})

    deleted = client.delete(f"/api/packages/{package_id}")
    assert deleted.status_code == 200
    assert workflow_store.get_workflow("wf_1", user.id) is not None
