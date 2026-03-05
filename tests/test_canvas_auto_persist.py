"""Tests for canvas workflow auto-persist behaviour.

When the frontend opens a new tab, it generates a wf_ UUID and sends it as
current_workflow_id in the chat payload. The socket handler must auto-create
a skeleton DB record for this ID so that all tools can load/edit it without
the LLM needing to call create_workflow first.

Verifies:
1. _sync_orchestrator_from_convo creates a DB record when ID is absent
2. Existing DB records are NOT overwritten on subsequent syncs
3. The orchestrator receives the correct current_workflow_id
4. System prompt tells LLM to use canvas ID directly (no create_workflow)
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.backend.api.conversations import ConversationStore
from src.backend.api.ws_chat import WsChatTask
from src.backend.storage.workflows import WorkflowStore
from uuid import uuid4
from src.backend.agents.system_prompt import build_system_prompt


@pytest.fixture
def workflow_store():
    """Create a temporary workflow store for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_workflows.sqlite"
        yield WorkflowStore(db_path)


@pytest.fixture
def convo_store():
    """Create a conversation store rooted in a temp directory."""
    return ConversationStore(repo_root=Path("."))


@pytest.fixture
def user_id():
    return "test_user_canvas"


def _generate_workflow_id() -> str:
    """Generate a unique workflow ID (replaces deleted CreateWorkflowTool helper)."""
    return f"wf_{uuid4().hex}"


def _make_task(
    workflow_store: WorkflowStore,
    convo_store: ConversationStore,
    user_id: str,
    *,
    current_workflow_id: str | None = None,
    conversation_id: str = "conv_test",
) -> WsChatTask:
    """Build a minimal WsChatTask with real stores but mocked registry."""
    task = WsChatTask(
        registry=MagicMock(),
        conversation_store=convo_store,
        repo_root=Path("."),
        workflow_store=workflow_store,
        user_id=user_id,
        conn_id="test_conn",
        task_id="task_test",
        message="hello",
        conversation_id=conversation_id,
        files_data=[],
        workflow=None,
        analysis=None,
        current_workflow_id=current_workflow_id,
    )
    # Create the conversation so _sync_orchestrator_from_convo can access it
    task.convo = convo_store.get_or_create(conversation_id)
    return task


class TestCanvasAutoPersist:
    """Auto-persist creates a skeleton DB record for the canvas workflow."""

    def test_creates_db_record_for_new_canvas_id(
        self, workflow_store, convo_store, user_id
    ):
        """When frontend sends a wf_ ID that's NOT in the DB, auto-create it."""
        canvas_id = _generate_workflow_id()
        task = _make_task(
            workflow_store, convo_store, user_id,
            current_workflow_id=canvas_id,
        )

        # Before sync: workflow does not exist
        assert workflow_store.get_workflow(canvas_id, user_id) is None

        task._sync_orchestrator_from_convo()

        # After sync: skeleton record exists in DB
        record = workflow_store.get_workflow(canvas_id, user_id)
        assert record is not None, "Auto-persist should create a DB record"
        assert record.id == canvas_id
        assert record.name == "New Workflow"
        assert record.is_draft is True

    def test_does_not_overwrite_existing_record(
        self, workflow_store, convo_store, user_id
    ):
        """When canvas ID already exists in DB, auto-persist should not clobber it."""
        canvas_id = _generate_workflow_id()

        # Pre-create a workflow with custom data
        workflow_store.create_workflow(
            workflow_id=canvas_id,
            user_id=user_id,
            name="My Custom Workflow",
            description="Pre-existing",
            nodes=[{"id": "node_1", "type": "start", "data": {"label": "Begin"}}],
            edges=[],
            inputs=[],
            outputs=[],
            output_type="number",
            is_draft=False,
        )

        task = _make_task(
            workflow_store, convo_store, user_id,
            current_workflow_id=canvas_id,
        )
        task._sync_orchestrator_from_convo()

        # Record should be untouched — not overwritten with skeleton defaults
        record = workflow_store.get_workflow(canvas_id, user_id)
        assert record is not None
        assert record.name == "My Custom Workflow"
        assert record.is_draft is False

    def test_orchestrator_receives_canvas_id(
        self, workflow_store, convo_store, user_id
    ):
        """After sync, the orchestrator's current_workflow_id matches the canvas ID."""
        canvas_id = _generate_workflow_id()
        task = _make_task(
            workflow_store, convo_store, user_id,
            current_workflow_id=canvas_id,
        )

        task._sync_orchestrator_from_convo()

        assert task.convo.orchestrator.current_workflow_id == canvas_id

    def test_no_id_means_no_persist(
        self, workflow_store, convo_store, user_id
    ):
        """When current_workflow_id is None, nothing is created or set."""
        task = _make_task(
            workflow_store, convo_store, user_id,
            current_workflow_id=None,
        )

        task._sync_orchestrator_from_convo()

        assert task.convo.orchestrator.current_workflow_id is None


class TestSystemPromptCanvasIntegration:
    """System prompt must instruct LLM to use canvas ID directly."""

    def test_prompt_shows_current_workflow_section(self):
        """When canvas ID is set, prompt must include Current Workflow section."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=[],
            allow_tools=True,
            current_workflow_id="wf_test123",
        )

        assert "### Current Workflow" in prompt
        assert "wf_test123" in prompt

    def test_prompt_describes_create_subworkflow(self):
        """The tool action mapping must say create_subworkflow is for sub-workflows."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=[],
            allow_tools=True,
            current_workflow_id="wf_test123",
        )

        assert "CREATE SUBWORKFLOW" in prompt
        # Old text should be gone
        assert "CREATE NEW WORKFLOW" not in prompt

    def test_implicit_workflow_binding(self):
        """Prompt should describe implicit workflow binding (no workflow_id needed)."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=[],
            allow_tools=True,
            current_workflow_id="wf_canvas_abc",
        )

        # Implicit binding: tools auto-target the current workflow
        assert "automatically target this workflow" in prompt
