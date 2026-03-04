"""Tests for the create_subworkflow tool.

Tests that:
1. Tool creates workflow in DB and returns workflow_id
2. Input variables are registered on the new workflow
3. Building flag is set on creation and cleared when done
4. Validation accepts subprocess nodes with building subworkflow_ids
5. get_subworkflow_output_type returns error for missing subworkflows
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from ..storage.workflows import WorkflowStore
from ..tools.workflow_analysis.create_subworkflow import CreateSubworkflowTool
from ..tools.workflow_edit.helpers import (
    get_subworkflow_output_type,
    validate_subprocess_node,
)


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


@pytest.fixture
def repo_root():
    """Repo root for tool construction."""
    return Path(__file__).resolve().parents[3]  # src/backend/tests -> project root


@pytest.fixture
def session_state(workflow_store, user_id, repo_root):
    """Standard session state for tool execution."""
    return {
        "workflow_store": workflow_store,
        "user_id": user_id,
        "repo_root": repo_root,
        "current_workflow": {"nodes": [], "edges": []},
        "workflow_analysis": {"variables": [], "outputs": []},
    }


class TestCreateSubworkflow:
    """Test create_subworkflow tool."""

    def test_creates_workflow_in_db(self, session_state, workflow_store, user_id):
        """Tool creates a workflow in the DB and returns its ID."""
        tool = CreateSubworkflowTool()

        result = tool.execute(
            {
                "name": "BMI Calculator",
                "output_type": "number",
                "brief": "Calculate BMI from weight and height. BMI = weight / height^2.",
                "inputs": [
                    {"name": "Weight", "type": "number", "description": "Weight in kg"},
                    {"name": "Height", "type": "number", "description": "Height in metres"},
                ],
            },
            session_state=session_state,
        )

        assert result["success"] is True, f"Failed: {result.get('error')}"
        assert "workflow_id" in result
        assert result["workflow_id"].startswith("wf_")
        assert result["status"] == "building"

        # Verify workflow exists in DB
        wf = workflow_store.get_workflow(result["workflow_id"], user_id)
        assert wf is not None
        assert wf.name == "BMI Calculator"
        assert wf.output_type == "number"
        assert wf.building is True  # Should be marked as building

    def test_registers_input_variables(self, session_state, workflow_store, user_id):
        """Tool registers declared input variables on the new workflow."""
        tool = CreateSubworkflowTool()

        result = tool.execute(
            {
                "name": "Score Calculator",
                "output_type": "number",
                "brief": "Calculate a score from age and income.",
                "inputs": [
                    {"name": "Age", "type": "number"},
                    {"name": "Income", "type": "number"},
                ],
            },
            session_state=session_state,
        )

        assert result["success"] is True
        assert len(result["registered_inputs"]) == 2

        # Verify variables are stored in the DB
        wf = workflow_store.get_workflow(result["workflow_id"], user_id)
        assert wf is not None
        input_names = [inp.get("name") for inp in wf.inputs]
        assert "Age" in input_names
        assert "Income" in input_names

    def test_rejects_missing_name(self, session_state):
        """Tool rejects calls with missing name."""
        tool = CreateSubworkflowTool()

        result = tool.execute(
            {
                "output_type": "string",
                "brief": "Some brief",
                "inputs": [],
            },
            session_state=session_state,
        )

        assert result["success"] is False
        assert "name" in result["error"].lower()

    def test_rejects_invalid_output_type(self, session_state):
        """Tool rejects calls with invalid output_type."""
        tool = CreateSubworkflowTool()

        result = tool.execute(
            {
                "name": "Test",
                "output_type": "invalid_type",
                "brief": "Some brief",
                "inputs": [],
            },
            session_state=session_state,
        )

        assert result["success"] is False
        assert "output_type" in result["error"].lower()

    def test_rejects_missing_brief(self, session_state):
        """Tool rejects calls with missing brief."""
        tool = CreateSubworkflowTool()

        result = tool.execute(
            {
                "name": "Test",
                "output_type": "string",
                "inputs": [],
            },
            session_state=session_state,
        )

        assert result["success"] is False
        assert "brief" in result["error"].lower()


class TestBuildingFlag:
    """Test the building flag on WorkflowStore."""

    def test_building_flag_persists(self, workflow_store, user_id):
        """Building flag is stored and retrieved correctly."""
        workflow_store.create_workflow(
            workflow_id="wf_test1",
            user_id=user_id,
            name="Test Building",
            description="",
            building=True,
        )

        wf = workflow_store.get_workflow("wf_test1", user_id)
        assert wf is not None
        assert wf.building is True

    def test_building_flag_cleared_via_update(self, workflow_store, user_id):
        """Building flag can be cleared via update_workflow."""
        workflow_store.create_workflow(
            workflow_id="wf_test2",
            user_id=user_id,
            name="Test Building 2",
            description="",
            building=True,
        )

        workflow_store.update_workflow("wf_test2", user_id, building=False)
        wf = workflow_store.get_workflow("wf_test2", user_id)
        assert wf is not None
        assert wf.building is False

    def test_building_defaults_to_false(self, workflow_store, user_id):
        """Building flag defaults to False when not specified."""
        workflow_store.create_workflow(
            workflow_id="wf_test3",
            user_id=user_id,
            name="Normal Workflow",
            description="",
        )

        wf = workflow_store.get_workflow("wf_test3", user_id)
        assert wf is not None
        assert wf.building is False


class TestSubworkflowValidation:
    """Test validation functions with building subworkflows."""

    def test_get_output_type_returns_error_for_missing(self, workflow_store, user_id):
        """get_subworkflow_output_type returns error dict for missing subworkflow."""
        session = {"workflow_store": workflow_store, "user_id": user_id}

        result = get_subworkflow_output_type("wf_nonexistent", session)
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_get_output_type_uses_declared_type_for_building(self, workflow_store, user_id):
        """get_subworkflow_output_type falls back to output_type for building workflows."""
        workflow_store.create_workflow(
            workflow_id="wf_building",
            user_id=user_id,
            name="Building Sub",
            description="",
            output_type="number",
            building=True,
        )

        session = {"workflow_store": workflow_store, "user_id": user_id}
        result = get_subworkflow_output_type("wf_building", session)

        assert "error" not in result
        assert result["type"] == "number"
        assert result.get("building") is True

    def test_validate_subprocess_accepts_building_subworkflow(self, workflow_store, user_id):
        """validate_subprocess_node accepts a building subworkflow as valid reference."""
        workflow_store.create_workflow(
            workflow_id="wf_building2",
            user_id=user_id,
            name="Building Sub 2",
            description="",
            output_type="string",
            building=True,
        )

        node = {
            "id": "node_sub_1",
            "type": "subprocess",
            "subworkflow_id": "wf_building2",
            "input_mapping": {},
            "output_variable": "Result",
        }

        session = {
            "workflow_store": workflow_store,
            "user_id": user_id,
            "workflow_analysis": {"variables": []},
        }

        errors = validate_subprocess_node(node, session, check_workflow_exists=True)
        # Should have no "not found" errors — building subworkflows are valid references
        not_found_errors = [e for e in errors if "not found" in e.lower()]
        assert len(not_found_errors) == 0, f"Unexpected errors: {errors}"

    def test_validate_subprocess_rejects_missing_subworkflow(self, workflow_store, user_id):
        """validate_subprocess_node rejects a subworkflow_id that doesn't exist."""
        node = {
            "id": "node_sub_2",
            "type": "subprocess",
            "subworkflow_id": "wf_does_not_exist",
            "input_mapping": {},
            "output_variable": "Result",
        }

        session = {
            "workflow_store": workflow_store,
            "user_id": user_id,
            "workflow_analysis": {"variables": []},
        }

        errors = validate_subprocess_node(node, session, check_workflow_exists=True)
        assert any("not found" in e.lower() for e in errors), f"Expected 'not found' error, got: {errors}"


    def test_input_mapping_error_lists_available_variables(self, workflow_store, user_id):
        """input_mapping error message includes available variable names for self-correction."""
        workflow_store.create_workflow(
            workflow_id="wf_sub_mapping",
            user_id=user_id,
            name="Mapping Test Sub",
            description="",
            output_type="string",
        )

        node = {
            "id": "node_sub_3",
            "type": "subprocess",
            "subworkflow_id": "wf_sub_mapping",
            "input_mapping": {"NonExistentVar": "sub_input"},
            "output_variable": "Result",
        }

        session = {
            "workflow_store": workflow_store,
            "user_id": user_id,
            "workflow_analysis": {
                "variables": [
                    {"name": "Age", "type": "number"},
                    {"name": "Income", "type": "number"},
                    {"name": "Has_Debt", "type": "bool"},
                ],
            },
        }

        errors = validate_subprocess_node(node, session, check_workflow_exists=True)
        # Should list available variable names in the error
        mapping_errors = [e for e in errors if "NonExistentVar" in e]
        assert len(mapping_errors) == 1
        assert "Available variables:" in mapping_errors[0]
        assert "Age" in mapping_errors[0]
        assert "Income" in mapping_errors[0]
        assert "Has_Debt" in mapping_errors[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
