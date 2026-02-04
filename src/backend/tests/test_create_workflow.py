"""Test create_workflow tool handles duplicate IDs correctly.

Tests that:
1. Creating a workflow with a fresh ID works
2. Creating multiple workflows when current_workflow_id is set doesn't cause UNIQUE constraint errors
3. If current_workflow_id already exists in DB, a new ID is generated instead
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ..storage.workflows import WorkflowStore
from ..tools.workflow_library.create_workflow import CreateWorkflowTool, generate_workflow_id


@pytest.fixture
def workflow_store():
    """Create a temporary workflow store for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_workflows.sqlite"
        yield WorkflowStore(db_path)


@pytest.fixture
def user_id():
    """Test user ID."""
    return "test_user_123"


class TestCreateWorkflow:
    """Test create_workflow tool."""

    def test_create_first_workflow_with_no_current_id(self, workflow_store, user_id):
        """Test creating a workflow when there's no current_workflow_id."""
        tool = CreateWorkflowTool()

        session_state = {
            "workflow_store": workflow_store,
            "user_id": user_id,
            "current_workflow_id": None,  # No existing workflow on canvas
        }

        result = tool.execute(
            {"name": "Test Workflow", "output_type": "string"},
            session_state=session_state,
        )

        assert result["success"] is True, f"Failed: {result.get('error')}"
        assert "workflow_id" in result
        assert result["workflow_id"].startswith("wf_")

    def test_create_first_workflow_with_current_id(self, workflow_store, user_id):
        """Test creating a workflow when current_workflow_id is set (first save of canvas)."""
        tool = CreateWorkflowTool()
        canvas_id = "wf_canvas123"  # ID from frontend canvas

        session_state = {
            "workflow_store": workflow_store,
            "user_id": user_id,
            "current_workflow_id": canvas_id,
        }

        result = tool.execute(
            {"name": "Canvas Workflow", "output_type": "string"},
            session_state=session_state,
        )

        assert result["success"] is True, f"Failed: {result.get('error')}"
        # Should use the canvas ID since it doesn't exist in DB yet
        assert result["workflow_id"] == canvas_id

    def test_create_second_workflow_generates_new_id(self, workflow_store, user_id):
        """Test that creating a second workflow generates a new ID, not reusing the first.

        This is the key bug fix test: when current_workflow_id points to an existing
        workflow in the DB, the tool should generate a NEW ID, not try to reuse it.
        """
        tool = CreateWorkflowTool()
        canvas_id = "wf_existing123"

        session_state = {
            "workflow_store": workflow_store,
            "user_id": user_id,
            "current_workflow_id": canvas_id,
        }

        # Create first workflow - uses canvas_id
        result1 = tool.execute(
            {"name": "First Workflow", "output_type": "string"},
            session_state=session_state,
        )
        assert result1["success"] is True, f"First create failed: {result1.get('error')}"
        assert result1["workflow_id"] == canvas_id

        # Create second workflow - should NOT fail with UNIQUE constraint
        # Instead, should generate a fresh ID
        result2 = tool.execute(
            {"name": "Second Workflow", "output_type": "int"},
            session_state=session_state,
        )
        assert result2["success"] is True, f"Second create failed: {result2.get('error')}"
        # Should have a DIFFERENT ID than the first
        assert result2["workflow_id"] != canvas_id
        assert result2["workflow_id"].startswith("wf_")

    def test_create_multiple_workflows_sequentially(self, workflow_store, user_id):
        """Test creating multiple workflows in sequence (simulates orchestrator behavior)."""
        tool = CreateWorkflowTool()
        canvas_id = "wf_session_canvas"

        session_state = {
            "workflow_store": workflow_store,
            "user_id": user_id,
            "current_workflow_id": canvas_id,
        }

        created_ids = set()

        # Create 5 workflows in sequence
        for i in range(5):
            result = tool.execute(
                {"name": f"Workflow {i+1}", "output_type": "string"},
                session_state=session_state,
            )
            assert result["success"] is True, f"Create #{i+1} failed: {result.get('error')}"

            # Each workflow should have a unique ID
            wf_id = result["workflow_id"]
            assert wf_id not in created_ids, f"Duplicate ID generated: {wf_id}"
            created_ids.add(wf_id)

        # All 5 should exist in the database
        workflows, count = workflow_store.list_workflows(user_id)
        assert count == 5, f"Expected 5 workflows, got {count}"

    def test_generate_workflow_id_uniqueness(self):
        """Test that generated workflow IDs are unique."""
        ids = {generate_workflow_id() for _ in range(1000)}
        # All 1000 should be unique
        assert len(ids) == 1000


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
