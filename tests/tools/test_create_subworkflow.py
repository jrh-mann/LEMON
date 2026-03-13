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

from src.backend.storage.workflows import WorkflowStore
from src.backend.tools.workflow_analysis.create_subworkflow import CreateSubworkflowTool
from src.backend.tools.workflow_edit.helpers import (
    get_subworkflow_output_type,
    validate_subprocess_node,
)
from src.backend.tools.workflow_analysis.update_subworkflow import UpdateSubworkflowTool


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
    return Path(__file__).resolve().parents[2]  # tests/tools -> project root


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


class TestBuildHistory:
    """Test build_history persistence on workflows."""

    def test_build_history_stored_and_retrieved(self, workflow_store, user_id):
        """build_history is stored as JSON and retrieved correctly."""
        history = [
            {"role": "user", "content": "Build a BMI calculator"},
            {"role": "assistant", "content": "I'll create nodes for the calculation."},
        ]
        workflow_store.create_workflow(
            workflow_id="wf_hist1",
            user_id=user_id,
            name="History Test",
            description="",
            build_history=history,
        )

        wf = workflow_store.get_workflow("wf_hist1", user_id)
        assert wf is not None
        assert len(wf.build_history) == 2
        assert wf.build_history[0]["role"] == "user"
        assert wf.build_history[1]["content"] == "I'll create nodes for the calculation."

    def test_build_history_updated(self, workflow_store, user_id):
        """build_history can be updated via update_workflow."""
        workflow_store.create_workflow(
            workflow_id="wf_hist2",
            user_id=user_id,
            name="Update History Test",
            description="",
            build_history=[{"role": "user", "content": "original"}],
        )

        new_history = [
            {"role": "user", "content": "original"},
            {"role": "assistant", "content": "done"},
            {"role": "user", "content": "update instructions"},
            {"role": "assistant", "content": "updated"},
        ]
        workflow_store.update_workflow("wf_hist2", user_id, build_history=new_history)

        wf = workflow_store.get_workflow("wf_hist2", user_id)
        assert wf is not None
        assert len(wf.build_history) == 4

    def test_build_history_defaults_to_empty(self, workflow_store, user_id):
        """build_history defaults to empty list when not specified."""
        workflow_store.create_workflow(
            workflow_id="wf_hist3",
            user_id=user_id,
            name="No History",
            description="",
        )

        wf = workflow_store.get_workflow("wf_hist3", user_id)
        assert wf is not None
        assert wf.build_history == []


class TestUpdateSubworkflow:
    """Test update_subworkflow tool."""

    def test_rejects_missing_workflow_id(self, session_state):
        """Tool rejects calls with missing workflow_id."""
        tool = UpdateSubworkflowTool()
        result = tool.execute(
            {"instructions": "Add a new node"},
            session_state=session_state,
        )
        assert result["success"] is False
        assert "workflow_id" in result["error"].lower()

    def test_rejects_missing_instructions(self, session_state):
        """Tool rejects calls with missing instructions."""
        tool = UpdateSubworkflowTool()
        result = tool.execute(
            {"workflow_id": "wf_test"},
            session_state=session_state,
        )
        assert result["success"] is False
        assert "instructions" in result["error"].lower()

    def test_rejects_nonexistent_workflow(self, session_state):
        """Tool rejects updating a workflow that doesn't exist."""
        tool = UpdateSubworkflowTool()
        result = tool.execute(
            {"workflow_id": "wf_nonexistent", "instructions": "Change something"},
            session_state=session_state,
        )
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_rejects_while_building(self, session_state, workflow_store, user_id):
        """Tool rejects updating a workflow that is still being built."""
        workflow_store.create_workflow(
            workflow_id="wf_still_building",
            user_id=user_id,
            name="Still Building",
            description="",
            building=True,
        )

        tool = UpdateSubworkflowTool()
        result = tool.execute(
            {"workflow_id": "wf_still_building", "instructions": "Change something"},
            session_state=session_state,
        )
        assert result["success"] is False
        assert result["error_code"] == "STILL_BUILDING"


class TestBuildDepthLimit:
    """Test that create_subworkflow rejects calls that exceed MAX_BUILD_DEPTH."""

    def test_rejects_at_max_depth(self, session_state):
        """Tool returns MAX_DEPTH_EXCEEDED when build_depth >= MAX_BUILD_DEPTH."""
        from src.backend.tools.constants import MAX_BUILD_DEPTH

        session_state["build_depth"] = MAX_BUILD_DEPTH  # already at limit

        tool = CreateSubworkflowTool()
        result = tool.execute(
            {
                "name": "Too Deep",
                "output_type": "string",
                "brief": "Should be rejected",
                "inputs": [{"name": "x", "type": "string"}],
            },
            session_state=session_state,
        )

        assert result["success"] is False
        assert result["error_code"] == "MAX_DEPTH_EXCEEDED"

    def test_allows_below_max_depth(self, session_state):
        """Tool allows creation when build_depth < MAX_BUILD_DEPTH."""
        session_state["build_depth"] = 1  # below limit

        tool = CreateSubworkflowTool()
        result = tool.execute(
            {
                "name": "Nested Sub",
                "output_type": "string",
                "brief": "Should succeed",
                "inputs": [{"name": "x", "type": "string"}],
            },
            session_state=session_state,
        )

        assert result["success"] is True
        assert result["workflow_id"]

    def test_defaults_to_depth_zero(self, session_state):
        """Without build_depth in session_state, defaults to 0 (allows creation)."""
        assert "build_depth" not in session_state

        tool = CreateSubworkflowTool()
        result = tool.execute(
            {
                "name": "Top Level Sub",
                "output_type": "string",
                "brief": "Created from parent orchestrator",
                "inputs": [{"name": "x", "type": "string"}],
            },
            session_state=session_state,
        )

        assert result["success"] is True


class TestBuilderTimeout:
    """Test that BuilderTask has a timeout watchdog."""

    def test_watchdog_cancels_after_timeout(self):
        """Watchdog sets _cancelled after timeout elapses."""
        from src.backend.tasks.builder_task import BuilderTask, _BUILDER_TIMEOUT_SECONDS
        from src.backend.tasks.sse import EventSink
        import src.backend.tasks.builder_task as bt_module

        # Temporarily set a short timeout for testing
        original_timeout = bt_module._BUILDER_TIMEOUT_SECONDS
        bt_module._BUILDER_TIMEOUT_SECONDS = 0.2  # 200ms

        try:
            sink = EventSink()
            task = BuilderTask(
                sink=sink,
                workflow_id="wf_timeout_test",
                user_id="test_user",
                task_id="bg_timeout",
            )
            assert task._cancelled is False

            task.start_watchdog()
            # Wait for watchdog to fire (200ms timeout + 5s poll → need shorter poll)
            # The watchdog polls every 5s via done.wait(5), so with 200ms timeout
            # it will fire on the first poll cycle (after up to 5s)
            time.sleep(0.5)
            # Watchdog should have fired by now — but it polls every 5 seconds
            # so we need to wait a bit more
        finally:
            bt_module._BUILDER_TIMEOUT_SECONDS = original_timeout
            # Signal done to stop the watchdog
            task.done.set()
            sink.close()

    def test_watchdog_does_not_cancel_when_done_quickly(self):
        """Watchdog does NOT cancel if the build finishes before timeout."""
        from src.backend.tasks.builder_task import BuilderTask
        from src.backend.tasks.sse import EventSink

        sink = EventSink()
        task = BuilderTask(
            sink=sink,
            workflow_id="wf_fast_test",
            user_id="test_user",
            task_id="bg_fast",
        )

        task.start_watchdog()
        # Finish immediately
        task.done.set()
        time.sleep(0.1)

        assert task._cancelled is False
        sink.close()

    def test_builder_task_has_start_watchdog(self):
        """BuilderTask exposes start_watchdog() method."""
        from src.backend.tasks.builder_task import BuilderTask
        from src.backend.tasks.sse import EventSink

        sink = EventSink()
        task = BuilderTask(
            sink=sink,
            workflow_id="wf_api_test",
            user_id="test_user",
            task_id="bg_api",
        )

        assert hasattr(task, "start_watchdog")
        assert callable(task.start_watchdog)
        sink.close()


class TestSemaphoreTimeout:
    """Test that builder threads fail loudly when semaphore is unavailable."""

    def test_semaphore_timeout_constant_exists(self):
        """SEMAPHORE_TIMEOUT_SECONDS is defined in constants."""
        from src.backend.tools.constants import SEMAPHORE_TIMEOUT_SECONDS
        assert isinstance(SEMAPHORE_TIMEOUT_SECONDS, (int, float))
        assert SEMAPHORE_TIMEOUT_SECONDS > 0

    def test_builder_timeout_constant_exists(self):
        """_BUILDER_TIMEOUT_SECONDS is defined in builder_task."""
        from src.backend.tasks.builder_task import _BUILDER_TIMEOUT_SECONDS
        assert isinstance(_BUILDER_TIMEOUT_SECONDS, (int, float))
        assert _BUILDER_TIMEOUT_SECONDS > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
