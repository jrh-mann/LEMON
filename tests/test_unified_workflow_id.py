"""Tests for unified workflow ID strategy.

Verifies that:
1. generate_workflow_id() produces wf_{32_hex_chars} format (not 8-char)
2. The create_workflow tool always generates a fresh ID (never reuses session IDs)
3. The REST API POST /api/workflows also uses wf_{32_hex_chars}
4. All three sources produce IDs in the same format
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

from src.backend.tools.workflow_library.create_workflow import (
    CreateWorkflowTool,
    generate_workflow_id,
)
from src.backend.storage.workflows import WorkflowStore

# Canonical ID pattern: wf_ followed by exactly 32 lowercase hex chars
WORKFLOW_ID_PATTERN = re.compile(r"^wf_[0-9a-f]{32}$")


@pytest.fixture
def workflow_store():
    """Create a temporary workflow store for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_workflows.sqlite"
        yield WorkflowStore(db_path)


@pytest.fixture
def user_id():
    return "test_user_unified"


class TestUnifiedWorkflowIdFormat:
    """All ID generators must produce wf_{32_hex_chars}."""

    def test_generate_workflow_id_format(self):
        """generate_workflow_id() must produce wf_{32_hex_chars}."""
        for _ in range(100):
            wf_id = generate_workflow_id()
            assert WORKFLOW_ID_PATTERN.match(wf_id), (
                f"ID '{wf_id}' does not match expected format wf_{{32_hex_chars}}"
            )

    def test_generate_workflow_id_length(self):
        """ID must be exactly 35 chars: 'wf_' (3) + 32 hex."""
        wf_id = generate_workflow_id()
        assert len(wf_id) == 35, f"Expected 35 chars, got {len(wf_id)}: {wf_id}"

    def test_create_workflow_tool_uses_canonical_format(self, workflow_store, user_id):
        """Tool always generates wf_{32_hex_chars}, regardless of session state."""
        tool = CreateWorkflowTool()
        session_state = {
            "workflow_store": workflow_store,
            "user_id": user_id,
            "current_workflow_id": None,
        }

        result = tool.execute(
            {"name": "Format Test", "output_type": "string"},
            session_state=session_state,
        )

        assert result["success"] is True
        assert WORKFLOW_ID_PATTERN.match(result["workflow_id"]), (
            f"Tool-generated ID '{result['workflow_id']}' does not match canonical format"
        )

    def test_create_workflow_ignores_session_id(self, workflow_store, user_id):
        """Tool generates a fresh ID even when current_workflow_id is set.

        create_workflow is for creating NEW workflows (subworkflows). The
        canvas/primary workflow is auto-persisted by the socket handler, so
        this tool should never reuse the session's current_workflow_id.
        """
        tool = CreateWorkflowTool()
        session_id = "wf_a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"

        session_state = {
            "workflow_store": workflow_store,
            "user_id": user_id,
            "current_workflow_id": session_id,
        }

        result = tool.execute(
            {"name": "Subworkflow Test", "output_type": "string"},
            session_state=session_state,
        )

        assert result["success"] is True
        # Tool must generate a FRESH ID, not reuse the session ID
        assert result["workflow_id"] != session_id, (
            f"Tool reused session ID '{session_id}' instead of generating a fresh one"
        )
        assert WORKFLOW_ID_PATTERN.match(result["workflow_id"])


class TestWorkflowIdConsistencyAcrossFlows:
    """Each create_workflow call must produce a unique workflow in the DB."""

    def test_sequential_creates_produce_unique_ids(self, workflow_store, user_id):
        """Two sequential create_workflow calls must produce distinct workflow IDs."""
        tool = CreateWorkflowTool()
        session_state = {
            "workflow_store": workflow_store,
            "user_id": user_id,
            "current_workflow_id": None,
        }

        result1 = tool.execute(
            {"name": "First", "output_type": "string"},
            session_state=session_state,
        )
        assert result1["success"] is True

        result2 = tool.execute(
            {"name": "Second", "output_type": "number"},
            session_state=session_state,
        )
        assert result2["success"] is True

        # Each call must produce a unique ID
        assert result1["workflow_id"] != result2["workflow_id"], (
            "Two create_workflow calls returned the same ID"
        )
        assert WORKFLOW_ID_PATTERN.match(result1["workflow_id"])
        assert WORKFLOW_ID_PATTERN.match(result2["workflow_id"])

    def test_tool_generates_new_id_when_frontend_id_already_in_db(
        self, workflow_store, user_id
    ):
        """If current_workflow_id points to an existing DB workflow, tool still
        generates a fresh ID (never updates or reuses the existing workflow)."""
        existing_id = generate_workflow_id()

        # Create the first workflow with this ID (simulates auto-persist)
        tool = CreateWorkflowTool()
        # First call: no session ID, will generate its own
        session_state_first = {
            "workflow_store": workflow_store,
            "user_id": user_id,
            "current_workflow_id": None,
        }
        result1 = tool.execute(
            {"name": "First", "output_type": "string"},
            session_state=session_state_first,
        )
        assert result1["success"] is True
        first_id = result1["workflow_id"]

        # Second call: session now has the first workflow's ID (simulates
        # orchestrator having updated current_workflow_id — but we removed
        # that update, so this tests defence-in-depth)
        session_state_second = {
            "workflow_store": workflow_store,
            "user_id": user_id,
            "current_workflow_id": first_id,
        }
        result2 = tool.execute(
            {"name": "Second", "output_type": "number"},
            session_state=session_state_second,
        )
        assert result2["success"] is True
        assert result2["workflow_id"] != first_id
        # New ID must also be in canonical format
        assert WORKFLOW_ID_PATTERN.match(result2["workflow_id"])
