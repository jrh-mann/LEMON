from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.api.routes.dev_tools_routes import register_dev_tools_routes
from src.backend.storage.auth import AuthUser
from src.backend.storage.workflows import WorkflowStore


def test_dev_tools_list_route_returns_tools_with_auth_override(tmp_path):
    app = FastAPI()
    workflow_store = WorkflowStore(tmp_path / "workflows.sqlite")
    register_dev_tools_routes(app, repo_root=Path.cwd(), workflow_store=workflow_store)

    from src.backend.api.routes import dev_tools_routes

    user = AuthUser(
        id="user_1",
        email="test@example.com",
        name="Test User",
        password_hash="hash",
        created_at="2026-01-01T00:00:00Z",
        last_login_at=None,
    )
    app.dependency_overrides[dev_tools_routes.require_auth] = lambda: user
    client = TestClient(app)
    response = client.get("/api/tools")

    assert response.status_code == 200
    assert len(response.json()["tools"]) > 0
    assert "name" in response.json()["tools"][0]
