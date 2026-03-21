"""Tests for POST /api/chat/cancel authorization behavior.

Verifies that the cancel endpoint returns 404 when the task is not found
or not owned by the requesting user, and 200 only on successful cancel.
"""

import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.api.routes import chat_routes
from src.backend.storage.auth import AuthUser
from src.backend.tasks.registry import TaskRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(user_id: str = "u1") -> AuthUser:
    return AuthUser(
        id=user_id,
        email=f"{user_id}@test.com",
        name="Test",
        password_hash="hash",
        created_at="2026-01-01T00:00:00Z",
        last_login_at=None,
    )


class _FakeTask:
    """Minimal task satisfying the Registrable protocol."""

    def __init__(self, task_id: str, user_id: str, workflow_id: str | None = None):
        self.task_id = task_id
        self.user_id = user_id
        self.current_workflow_id = workflow_id
        self._cancelled = False
        self._notified = False
        self._created_at = time.monotonic()
        self.sink = _FakeSink()


class _FakeSink:
    """EventSink stub that records pushed events."""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def push(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCancelRoute:
    """POST /api/chat/cancel returns 404 when task missing or not owned."""

    def _build_client(self, registry: TaskRegistry, user: AuthUser) -> TestClient:
        """Wire up a minimal FastAPI app with the chat cancel route."""
        from unittest.mock import MagicMock
        from pathlib import Path

        app = FastAPI()
        chat_routes.register_chat_routes(
            app,
            conversation_store=MagicMock(),
            repo_root=Path.cwd(),
            conversation_logger=MagicMock(),
            workflow_store=MagicMock(),
        )
        # Override the module-level singleton so our tests control it
        chat_routes.task_registry = registry
        app.dependency_overrides[chat_routes.require_auth] = lambda: user
        return TestClient(app)

    def test_cancel_nonexistent_task_returns_404(self):
        registry = TaskRegistry()
        client = self._build_client(registry, _make_user("u1"))

        resp = client.post("/api/chat/cancel", json={"task_id": "no-such-task"})
        assert resp.status_code == 404
        assert "error" in resp.json()

    def test_cancel_wrong_user_returns_404(self):
        registry = TaskRegistry()
        task = _FakeTask("t1", user_id="owner")
        registry.register(task)

        # Request as a different user
        client = self._build_client(registry, _make_user("attacker"))
        resp = client.post("/api/chat/cancel", json={"task_id": "t1"})

        assert resp.status_code == 404
        assert "error" in resp.json()
        assert not task._cancelled  # task must NOT be cancelled

    def test_cancel_own_task_returns_200(self):
        registry = TaskRegistry()
        task = _FakeTask("t1", user_id="u1", workflow_id="w1")
        registry.register(task)

        client = self._build_client(registry, _make_user("u1"))
        resp = client.post("/api/chat/cancel", json={"task_id": "t1"})

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert task._cancelled
