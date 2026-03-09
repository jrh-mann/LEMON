from src.backend.api.routes.execution_routes import register_execution_routes
from src.backend.api import routes as api_routes
from src.backend.api.ws_execution import handle_execute_workflow
from src.backend.storage.auth import AuthUser
from src.backend.storage.workflows import WorkflowStore
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pathlib import Path
from datetime import datetime, timezone
import tempfile


class _RegistryStub:
    def __init__(self):
        self.events = []

    def send_to_sync(self, conn_id, event, payload):
        self.events.append((conn_id, event, payload))


def _make_store() -> WorkflowStore:
    tmpdir = tempfile.TemporaryDirectory()
    store = WorkflowStore(Path(tmpdir.name) / "workflows.sqlite")
    store._tmpdir = tmpdir
    return store


def test_rest_and_ws_execution_share_validation_and_output(monkeypatch):
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

    app = FastAPI()
    register_execution_routes(app, workflow_store=store)
    app.dependency_overrides[api_routes.execution_routes.require_auth] = lambda: user
    client = TestClient(app)

    rest_response = client.post("/api/execute/wf_exec", json={})
    assert rest_response.status_code == 200
    assert rest_response.json()["output"] == 42.0

    registry = _RegistryStub()
    handle_execute_workflow(
        registry,
        conn_id="conn",
        workflow_store=store,
        user_id=user.id,
        payload={
            "workflow": {
                "nodes": [
                    {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0, "color": "teal"},
                    {"id": "end", "type": "end", "label": "Result", "x": 100, "y": 0, "color": "green", "output_value": "42"},
                ],
                "edges": [{"id": "e1", "from": "start", "to": "end", "label": ""}],
                "variables": [],
                "outputs": [{"name": "Result", "type": "number"}],
                "output_type": "number",
            },
            "inputs": {},
            "speed_ms": 0,
            "execution_id": "exec_1",
        },
    )

    complete_events = [event for event in registry.events if event[1] == "execution_complete"]
    assert complete_events
    assert complete_events[-1][2]["output"] == 42.0
