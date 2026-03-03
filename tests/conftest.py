"""Shared test fixtures for workflow tool tests.

All workflow tools now require workflow_id parameter and load/save from database.
These fixtures provide a standard way to set up test workflows.
"""

import pytest
import tempfile
from pathlib import Path
from typing import Any, Dict, Generator, Tuple

from src.backend.storage.workflows import WorkflowStore
from src.backend.tools import CreateWorkflowTool


@pytest.fixture
def workflow_store() -> Generator[WorkflowStore, None, None]:
    """Create a temporary workflow store for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_workflows.sqlite"
        store = WorkflowStore(db_path)
        yield store


@pytest.fixture
def test_user_id() -> str:
    """Standard test user ID."""
    return "test_user_123"


@pytest.fixture
def session_state(workflow_store: WorkflowStore, test_user_id: str) -> Dict[str, Any]:
    """Create a session state dict with workflow_store and user_id."""
    return {
        "workflow_store": workflow_store,
        "user_id": test_user_id,
    }


@pytest.fixture
def create_workflow_tool() -> CreateWorkflowTool:
    """Create workflow tool instance."""
    return CreateWorkflowTool()


@pytest.fixture
def create_test_workflow(
    create_workflow_tool: CreateWorkflowTool,
    session_state: Dict[str, Any],
):
    """Factory fixture to create test workflows.
    
    Returns a function that creates a workflow and returns (workflow_id, session_state).
    """
    def _create(
        name: str = "Test Workflow",
        output_type: str = "string",
        description: str = "",
    ) -> Tuple[str, Dict[str, Any]]:
        result = create_workflow_tool.execute(
            {"name": name, "output_type": output_type, "description": description},
            session_state=session_state,
        )
        assert result["success"], f"Failed to create workflow: {result}"
        return result["workflow_id"], session_state
    
    return _create


def make_session_with_workflow(
    workflow_store: WorkflowStore,
    user_id: str,
    nodes: list = None,
    edges: list = None,
    variables: list = None,
    output_type: str = "string",
    name: str = "Test Workflow",
) -> Tuple[str, Dict[str, Any]]:
    """Helper to create a workflow with initial data and return (workflow_id, session_state).
    
    This is useful for tests that need a workflow with pre-existing nodes/edges.
    """
    # Create the workflow
    create_tool = CreateWorkflowTool()
    session_state = {"workflow_store": workflow_store, "user_id": user_id}
    
    result = create_tool.execute(
        {"name": name, "output_type": output_type},
        session_state=session_state,
    )
    assert result["success"], f"Failed to create workflow: {result}"
    workflow_id = result["workflow_id"]
    
    # If we need to add initial nodes/edges, update the workflow directly
    if nodes or edges or variables:
        record = workflow_store.get_workflow(workflow_id, user_id)
        workflow_store.update_workflow(
            workflow_id=workflow_id,
            user_id=user_id,
            nodes=nodes if nodes else record.nodes,
            edges=edges if edges else record.edges,
            inputs=variables if variables else record.inputs,
        )
    
    return workflow_id, session_state
