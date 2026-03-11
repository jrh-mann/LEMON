"""Shared test fixtures for backend integration tests.

Provides a properly-configured orchestrator with a real WorkflowStore
(SQLite in tmp_path) and a test workflow record. This mirrors how the
real app sets up orchestrator state — tools load from DB, not from
in-memory dicts.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from ..agents.orchestrator import Orchestrator
from ..agents.orchestrator_factory import build_orchestrator
from ..storage.workflows import WorkflowStore


def _repo_root() -> Path:
    return Path(__file__).parent.parent.parent.parent


@pytest.fixture
def orchestrator_with_workflow(tmp_path) -> Orchestrator:
    """Create an orchestrator backed by a real SQLite WorkflowStore.

    Sets up:
    - WorkflowStore with a test workflow record in the DB
    - orchestrator.current_workflow_id pointing to that workflow
    - orchestrator.user_id set to a test user

    This is the standard fixture for any test that exercises workflow
    tools (add_node, add_connection, add_workflow_variable, etc.).
    """
    orch = build_orchestrator(repo_root=_repo_root())

    # Create real SQLite workflow store in tmp_path
    db_path = tmp_path / "test_workflows.sqlite"
    workflow_store = WorkflowStore(db_path)

    test_user_id = f"test_user_{uuid4().hex[:8]}"
    workflow_id = f"wf_test_{uuid4().hex[:8]}"

    # Create the workflow record directly in the DB — no "create_workflow"
    # tool needed. This is what the frontend/API does before tools run.
    workflow_store.create_workflow(
        workflow_id=workflow_id,
        user_id=test_user_id,
        name="Test Workflow",
        description="Test workflow for integration tests",
        output_type="string",
        is_draft=False,
    )

    # Wire up the orchestrator
    orch.workflow_store = workflow_store
    orch.user_id = test_user_id
    orch.current_workflow_id = workflow_id

    # Load initial (empty) state from DB so orchestrator.workflow is populated
    orch.refresh_workflow_from_db()

    return orch
