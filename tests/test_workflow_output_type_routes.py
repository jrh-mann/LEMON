"""Tests for workflow-level output_type persistence through save/load.

Verifies that output_type is stored and retrieved correctly via the
WorkflowStore, and that _infer_outputs_from_nodes uses the workflow-level
output_type instead of per-node output_type.
"""

import tempfile
from pathlib import Path

import pytest

from src.backend.storage.workflows import WorkflowStore
from src.backend.api.routes import _infer_outputs_from_nodes


@pytest.fixture
def workflow_store():
    """Create a temporary workflow store for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_workflows.sqlite"
        store = WorkflowStore(db_path)
        yield store


class TestOutputTypePersistence:
    """Test that output_type is saved and loaded correctly."""

    def test_create_workflow_with_output_type(self, workflow_store):
        """Save workflow with output_type='number', reload it, confirm it persists."""
        workflow_store.create_workflow(
            workflow_id="wf_test_1",
            user_id="user_1",
            name="Test Number Workflow",
            description="Returns a number",
            output_type="number",
        )

        loaded = workflow_store.get_workflow("wf_test_1", "user_1")
        assert loaded is not None
        assert loaded.output_type == "number"

    def test_create_workflow_default_output_type(self, workflow_store):
        """Workflow without explicit output_type defaults to 'string'."""
        workflow_store.create_workflow(
            workflow_id="wf_test_2",
            user_id="user_1",
            name="Test Default Workflow",
            description="",
        )

        loaded = workflow_store.get_workflow("wf_test_2", "user_1")
        assert loaded is not None
        assert loaded.output_type == "string"

    def test_update_workflow_output_type(self, workflow_store):
        """Update output_type on existing workflow and confirm it persists."""
        workflow_store.create_workflow(
            workflow_id="wf_test_3",
            user_id="user_1",
            name="Test Update Workflow",
            description="",
            output_type="string",
        )

        # Update to bool
        success = workflow_store.update_workflow(
            workflow_id="wf_test_3",
            user_id="user_1",
            output_type="bool",
        )
        assert success

        loaded = workflow_store.get_workflow("wf_test_3", "user_1")
        assert loaded is not None
        assert loaded.output_type == "bool"

    def test_all_output_types_persist(self, workflow_store):
        """All supported output_type values persist correctly."""
        for otype in ("string", "number", "bool", "json"):
            wf_id = f"wf_type_{otype}"
            workflow_store.create_workflow(
                workflow_id=wf_id,
                user_id="user_1",
                name=f"Test {otype} Workflow",
                description="",
                output_type=otype,
            )
            loaded = workflow_store.get_workflow(wf_id, "user_1")
            assert loaded is not None, f"Failed to load workflow for output_type={otype}"
            assert loaded.output_type == otype, (
                f"Expected output_type='{otype}', got '{loaded.output_type}'"
            )


class TestInferOutputsFromNodes:
    """Test _infer_outputs_from_nodes uses workflow-level output_type."""

    def test_uses_workflow_output_type(self):
        """End nodes get the workflow-level output_type, not per-node."""
        nodes = [
            {"type": "start", "id": "start_1", "label": "Start"},
            {"type": "end", "id": "end_1", "label": "Result"},
        ]
        outputs = _infer_outputs_from_nodes(nodes, workflow_output_type="number")
        assert len(outputs) == 1
        assert outputs[0]["type"] == "number"
        assert outputs[0]["name"] == "Result"

    def test_default_workflow_output_type_is_string(self):
        """Default workflow_output_type should be 'string'."""
        nodes = [{"type": "end", "id": "end_1", "label": "Output"}]
        outputs = _infer_outputs_from_nodes(nodes)
        assert len(outputs) == 1
        assert outputs[0]["type"] == "string"

    def test_multiple_end_nodes_same_type(self):
        """All end nodes use the same workflow-level output_type."""
        nodes = [
            {"type": "end", "id": "end_1", "label": "High Risk"},
            {"type": "end", "id": "end_2", "label": "Low Risk"},
        ]
        outputs = _infer_outputs_from_nodes(nodes, workflow_output_type="bool")
        assert len(outputs) == 2
        assert all(o["type"] == "bool" for o in outputs)

    def test_non_end_nodes_ignored(self):
        """Only end nodes produce outputs."""
        nodes = [
            {"type": "start", "id": "start_1", "label": "Start"},
            {"type": "decision", "id": "dec_1", "label": "Check"},
            {"type": "end", "id": "end_1", "label": "Done"},
        ]
        outputs = _infer_outputs_from_nodes(nodes, workflow_output_type="json")
        assert len(outputs) == 1
        assert outputs[0]["name"] == "Done"
        assert outputs[0]["type"] == "json"

    def test_output_template_included_as_description(self):
        """End nodes with output_template include it as description."""
        nodes = [
            {
                "type": "end",
                "id": "end_1",
                "label": "Score",
                "output_template": "Patient score: {Score}",
            },
        ]
        outputs = _infer_outputs_from_nodes(nodes, workflow_output_type="string")
        assert len(outputs) == 1
        assert outputs[0]["description"] == "Patient score: {Score}"
