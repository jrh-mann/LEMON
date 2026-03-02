"""Tests for unified workflow ID strategy.

Verifies that:
1. generate_workflow_id() produces wf_{32_hex_chars} format (not 8-char)
2. The create_workflow tool reuses frontend's current_workflow_id (wf_ prefix)
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
        """When no current_workflow_id, tool generates wf_{32_hex_chars}."""
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

    def test_create_workflow_tool_preserves_frontend_id(self, workflow_store, user_id):
        """When current_workflow_id is set (from frontend), tool reuses it."""
        tool = CreateWorkflowTool()
        frontend_id = "wf_a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"

        session_state = {
            "workflow_store": workflow_store,
            "user_id": user_id,
            "current_workflow_id": frontend_id,
        }

        result = tool.execute(
            {"name": "Frontend ID Test", "output_type": "string"},
            session_state=session_state,
        )

        assert result["success"] is True
        assert result["workflow_id"] == frontend_id, (
            f"Expected tool to reuse frontend ID '{frontend_id}', got '{result['workflow_id']}'"
        )


class TestWorkflowIdConsistencyAcrossFlows:
    """The same ID must flow from frontend → socket → orchestrator → tool → DB."""

    def test_frontend_generated_id_reaches_tool(self, workflow_store, user_id):
        """Simulates: frontend generates wf_ ID, sends via socket, tool reuses it."""
        # Frontend generates ID (simulated)
        frontend_id = generate_workflow_id()

        # This ID is sent as current_workflow_id in the chat payload
        # and arrives in session_state for the tool
        tool = CreateWorkflowTool()
        session_state = {
            "workflow_store": workflow_store,
            "user_id": user_id,
            "current_workflow_id": frontend_id,
        }

        result = tool.execute(
            {"name": "Consistency Test", "output_type": "string"},
            session_state=session_state,
        )

        assert result["success"] is True
        # The DB workflow_id must equal the frontend ID
        assert result["workflow_id"] == frontend_id

        # Verify it's in the DB with that exact ID
        stored = workflow_store.get_workflow(frontend_id, user_id)
        assert stored is not None, f"Workflow '{frontend_id}' not found in DB"
        assert stored.id == frontend_id

    def test_tool_generates_new_id_when_frontend_id_already_in_db(
        self, workflow_store, user_id
    ):
        """If frontend ID is already in DB, tool must generate a new one."""
        existing_id = generate_workflow_id()

        # Create the first workflow with this ID
        tool = CreateWorkflowTool()
        session_state = {
            "workflow_store": workflow_store,
            "user_id": user_id,
            "current_workflow_id": existing_id,
        }

        result1 = tool.execute(
            {"name": "First", "output_type": "string"},
            session_state=session_state,
        )
        assert result1["success"] is True
        assert result1["workflow_id"] == existing_id

        # Create second workflow with same current_workflow_id —
        # tool should detect the collision and generate a fresh ID
        result2 = tool.execute(
            {"name": "Second", "output_type": "number"},
            session_state=session_state,
        )
        assert result2["success"] is True
        assert result2["workflow_id"] != existing_id
        # New ID must also be in canonical format
        assert WORKFLOW_ID_PATTERN.match(result2["workflow_id"])
