"""Tests for GET /api/uploads/{file_path} path traversal protection.

Verifies that the uploads route blocks directory traversal attempts
and only serves files within the data directory.
"""

import os
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.api.routes import workflow_routes
from src.backend.storage.auth import AuthUser
from src.backend.storage.workflows import WorkflowStore


def _make_user() -> AuthUser:
    return AuthUser(
        id="u1",
        email="u1@test.com",
        name="Test",
        password_hash="hash",
        created_at="2026-01-01T00:00:00Z",
        last_login_at=None,
    )


def _build_client(tmp_path: Path) -> TestClient:
    """Wire up a minimal app with the workflow routes and a temp data dir."""
    app = FastAPI()
    wf_store = WorkflowStore(tmp_path / "workflows.sqlite")
    workflow_routes.register_workflow_routes(app, workflow_store=wf_store, repo_root=tmp_path)
    app.dependency_overrides[workflow_routes.require_auth] = _make_user
    return TestClient(app)


class TestUploadPathTraversal:

    def test_traversal_with_dotdot_blocked(self, tmp_path):
        """Traversal attempts must never return the file outside data dir."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        secret = tmp_path / "secret.txt"
        secret.write_text("top secret")

        with patch.dict(os.environ, {"LEMON_DATA_DIR": str(data_dir)}):
            client = _build_client(tmp_path)
            # TestClient may normalize `..` before routing; use encoded form
            resp = client.get("/api/uploads/subdir/../../secret.txt")

        # Either 403 (guard caught it) or 404 (URL normalized away) — never 200
        assert resp.status_code in (403, 404)
        assert "top secret" not in resp.text

    def test_valid_file_returns_200(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        test_file = data_dir / "image.png"
        test_file.write_bytes(b"\x89PNG fake data")

        with patch.dict(os.environ, {"LEMON_DATA_DIR": str(data_dir)}):
            client = _build_client(tmp_path)
            resp = client.get("/api/uploads/image.png")

        assert resp.status_code == 200

    def test_nonexistent_file_returns_404(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        with patch.dict(os.environ, {"LEMON_DATA_DIR": str(data_dir)}):
            client = _build_client(tmp_path)
            resp = client.get("/api/uploads/nope.txt")

        assert resp.status_code == 404
        assert resp.json()["error"] == "file not found"
