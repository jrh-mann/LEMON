"""Tests for unified workflow ID strategy.

Verifies that:
1. generate_workflow_id() produces wf_{32_hex_chars} format (not 8-char)
2. WorkflowStore.create_workflow() stores workflows with canonical IDs
3. Sequential creates produce unique IDs
4. All sources produce IDs in the same format
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

from src.backend.tools.constants import generate_workflow_id
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

    def test_workflow_store_create_uses_canonical_format(self, workflow_store, user_id):
        """WorkflowStore.create_workflow() with a generated ID stores it correctly."""
        wf_id = generate_workflow_id()
        assert WORKFLOW_ID_PATTERN.match(wf_id), (
            f"Generated ID '{wf_id}' does not match canonical format"
        )

        workflow_store.create_workflow(
            workflow_id=wf_id,
            user_id=user_id,
            name="Format Test",
            description="",
            output_type="string",
        )

        # Verify it was stored and retrievable
        record = workflow_store.get_workflow(wf_id, user_id)
        assert record is not None
        assert record.name == "Format Test"

    def test_generate_workflow_id_always_fresh(self, workflow_store, user_id):
        """Each call to generate_workflow_id() produces a new unique ID."""
        existing_id = generate_workflow_id()
        workflow_store.create_workflow(
            workflow_id=existing_id,
            user_id=user_id,
            name="First",
            description="",
            output_type="string",
        )

        # Generate a second ID — must differ from the first
        new_id = generate_workflow_id()
        assert new_id != existing_id, (
            f"generate_workflow_id() returned the same ID twice: {existing_id}"
        )
        assert WORKFLOW_ID_PATTERN.match(new_id)


class TestWorkflowIdConsistencyAcrossFlows:
    """Each workflow creation must produce a unique workflow in the DB."""

    def test_sequential_creates_produce_unique_ids(self, workflow_store, user_id):
        """Two sequential create calls must produce distinct workflow IDs."""
        wf_id_1 = generate_workflow_id()
        workflow_store.create_workflow(
            workflow_id=wf_id_1,
            user_id=user_id,
            name="First",
            description="",
            output_type="string",
        )

        wf_id_2 = generate_workflow_id()
        workflow_store.create_workflow(
            workflow_id=wf_id_2,
            user_id=user_id,
            name="Second",
            description="",
            output_type="number",
        )

        # Each call must produce a unique ID
        assert wf_id_1 != wf_id_2, (
            "Two create calls returned the same ID"
        )
        assert WORKFLOW_ID_PATTERN.match(wf_id_1)
        assert WORKFLOW_ID_PATTERN.match(wf_id_2)

    def test_created_workflows_are_independently_retrievable(
        self, workflow_store, user_id
    ):
        """Both workflows should be independently retrievable from the store."""
        wf_id_1 = generate_workflow_id()
        workflow_store.create_workflow(
            workflow_id=wf_id_1,
            user_id=user_id,
            name="First",
            description="",
            output_type="string",
        )

        wf_id_2 = generate_workflow_id()
        workflow_store.create_workflow(
            workflow_id=wf_id_2,
            user_id=user_id,
            name="Second",
            description="",
            output_type="number",
        )

        record_1 = workflow_store.get_workflow(wf_id_1, user_id)
        record_2 = workflow_store.get_workflow(wf_id_2, user_id)
        assert record_1 is not None
        assert record_2 is not None
        assert record_1.name == "First"
        assert record_2.name == "Second"
        assert WORKFLOW_ID_PATTERN.match(wf_id_1)
        assert WORKFLOW_ID_PATTERN.match(wf_id_2)
