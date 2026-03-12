"""Tests for parity between REST and stepped execution (SSE) paths."""

from src.backend.api.routes.execution_routes import register_execution_routes
from src.backend.api import routes as api_routes
from src.backend.api.execution_task import (
    SteppedExecutionTask,
    register_execution,
)
from src.backend.api.sse import EventSink
from src.backend.storage.auth import AuthUser
from src.backend.storage.workflows import WorkflowStore
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pathlib import Path
from datetime import datetime, timezone
import tempfile


def _make_store() -> WorkflowStore:
    tmpdir = tempfile.TemporaryDirectory()
    store = WorkflowStore(Path(tmpdir.name) / "workflows.sqlite")
    store._tmpdir = tmpdir
    return store


def test_rest_and_sse_execution_share_validation_and_output(monkeypatch):
    """REST execute endpoint and SteppedExecutionTask must produce identical outputs."""
    store = _make_store()
    now = datetime.now(timezone.utc).isoformat()
    user = AuthUser(
        id="user_1",
        email="test@example.com",
        name="Test User",
        password_hash="hash",
        created_at=now,
        last_login_at=None,
    )
    store.create_workflow(
        workflow_id="wf_exec",
        user_id=user.id,
        name="Exec",
        description="",
        nodes=[
            {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0, "color": "teal"},
            {"id": "end", "type": "end", "label": "Result", "x": 100, "y": 0, "color": "green", "output_value": "42"},
        ],
        edges=[{"id": "e1", "from": "start", "to": "end", "label": ""}],
        inputs=[],
        outputs=[{"name": "Result", "type": "number"}],
        output_type="number",
        tree={"stale": True},
    )

    # --- REST path ---
    app = FastAPI()
    register_execution_routes(app, workflow_store=store)
    app.dependency_overrides[api_routes.execution_routes.require_auth] = lambda: user
    client = TestClient(app)

    rest_response = client.post("/api/execute/wf_exec", json={})
    assert rest_response.status_code == 200
    assert rest_response.json()["output"] == 42.0

    # --- SSE stepped execution path ---
    # Collect all events pushed to the sink
    collected: list[tuple[str, dict]] = []

    class _RecordingSink(EventSink):
        """EventSink that records pushes for assertion without blocking iteration."""
        def push(self, event: str, data: dict) -> None:
            collected.append((event, data))
            super().push(event, data)

    sink = _RecordingSink()
    execution_id = "exec_1"
    workflow = {
        "nodes": [
            {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0, "color": "teal"},
            {"id": "end", "type": "end", "label": "Result", "x": 100, "y": 0, "color": "green", "output_value": "42"},
        ],
        "edges": [{"id": "e1", "from": "start", "to": "end", "label": ""}],
        "variables": [],
        "outputs": [{"name": "Result", "type": "number"}],
        "output_type": "number",
    }

    register_execution(execution_id)
    task = SteppedExecutionTask(
        sink=sink,
        workflow_store=store,
        user_id=user.id,
        execution_id=execution_id,
        workflow=workflow,
        inputs={},
        speed_ms=0,
    )
    task.run()

    complete_events = [(ev, data) for ev, data in collected if ev == "execution_complete"]
    assert complete_events, "Expected at least one execution_complete event"
    assert complete_events[-1][1]["output"] == 42.0
