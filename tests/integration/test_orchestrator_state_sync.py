"""Integration tests: verify orchestrator state stays in sync with DB after tool calls.

These tests exercise the full tool execution path through orchestrator.run_tool(),
then compare the orchestrator's in-memory workflow state against what's persisted
in the SQLite database. This ensures no drift between the two after each operation.

Phase 0 safety net: these tests capture current behavior before architectural changes.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Reduce log noise during test runs
os.environ.setdefault("LEMON_LOG_LEVEL", "WARNING")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.agents.orchestrator_factory import build_orchestrator
from src.backend.storage.workflows import WorkflowStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_orchestrator_and_workflow():
    """Set up a fresh orchestrator + temp DB + empty workflow.

    Returns (orchestrator, workflow_store, workflow_id, user_id).
    """
    orchestrator = build_orchestrator(PROJECT_ROOT)

    tmp_dir = tempfile.mkdtemp(prefix="lemon_state_sync_test_")
    db_path = Path(tmp_dir) / "test.sqlite"
    workflow_store = WorkflowStore(db_path)

    workflow_id = "wf_state_sync_test"
    user_id = "test_user"

    # Create an empty workflow in the database
    workflow_store.create_workflow(
        workflow_id=workflow_id,
        user_id=user_id,
        name="State Sync Test",
        description="",
    )

    # Wire up orchestrator to the DB-backed workflow
    orchestrator.workflow_store = workflow_store
    orchestrator.user_id = user_id
    orchestrator.current_workflow_id = workflow_id
    orchestrator.current_workflow_name = "State Sync Test"
    orchestrator.repo_root = PROJECT_ROOT

    return orchestrator, workflow_store, workflow_id, user_id


def _load_db_workflow(workflow_store, workflow_id, user_id):
    """Load the workflow record from DB and return a dict with nodes/edges/variables."""
    record = workflow_store.get_workflow(workflow_id, user_id)
    assert record is not None, f"Workflow {workflow_id} not found in DB"
    return {
        "nodes": record.nodes,
        "edges": record.edges,
        # DB stores variables in the 'inputs' field
        "variables": record.inputs,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_add_node_syncs_to_db():
    """After add_node, the node must appear in both orchestrator memory and DB."""
    orchestrator, store, wf_id, user_id = _make_orchestrator_and_workflow()

    result = orchestrator.run_tool("add_node", {
        "type": "process",
        "label": "Test Node",
        "x": 0,
        "y": 0,
    })
    assert result.success, f"add_node failed: {result.error}"

    # Verify orchestrator in-memory state has the node
    mem_nodes = orchestrator.workflow["nodes"]
    assert len(mem_nodes) == 1, f"Expected 1 node in memory, got {len(mem_nodes)}"
    assert mem_nodes[0]["label"] == "Test Node"

    # Verify DB state matches
    db_state = _load_db_workflow(store, wf_id, user_id)
    assert len(db_state["nodes"]) == 1, f"Expected 1 node in DB, got {len(db_state['nodes'])}"
    assert db_state["nodes"][0]["label"] == "Test Node"

    # IDs must match between memory and DB
    assert mem_nodes[0]["id"] == db_state["nodes"][0]["id"]


def test_add_variable_syncs_to_db():
    """After add_workflow_variable, the variable must appear in both memory and DB."""
    orchestrator, store, wf_id, user_id = _make_orchestrator_and_workflow()

    result = orchestrator.run_tool("add_workflow_variable", {
        "name": "Patient Age",
        "type": "number",
        "description": "Age in years",
    })
    assert result.success, f"add_workflow_variable failed: {result.error}"

    # Verify orchestrator in-memory state has the variable
    mem_vars = orchestrator.workflow["variables"]
    assert len(mem_vars) == 1, f"Expected 1 variable in memory, got {len(mem_vars)}"
    assert mem_vars[0]["name"] == "Patient Age"
    assert mem_vars[0]["type"] == "number"

    # Verify DB state matches
    db_state = _load_db_workflow(store, wf_id, user_id)
    assert len(db_state["variables"]) == 1, f"Expected 1 variable in DB, got {len(db_state['variables'])}"
    assert db_state["variables"][0]["name"] == "Patient Age"
    assert db_state["variables"][0]["type"] == "number"

    # IDs must match
    assert mem_vars[0]["id"] == db_state["variables"][0]["id"]


def test_add_connection_syncs_to_db():
    """After adding two nodes and connecting them, the edge must be in both places."""
    orchestrator, store, wf_id, user_id = _make_orchestrator_and_workflow()

    # Add two nodes
    r1 = orchestrator.run_tool("add_node", {
        "type": "start",
        "label": "Start",
        "x": 0,
        "y": 0,
    })
    assert r1.success, f"add_node (start) failed: {r1.error}"

    r2 = orchestrator.run_tool("add_node", {
        "type": "process",
        "label": "Step 1",
        "x": 200,
        "y": 0,
    })
    assert r2.success, f"add_node (process) failed: {r2.error}"

    # Get node IDs from the orchestrator's in-memory state
    start_id = orchestrator.workflow["nodes"][0]["id"]
    step_id = orchestrator.workflow["nodes"][1]["id"]

    # Add connection between them
    r3 = orchestrator.run_tool("add_connection", {
        "from_node_id": start_id,
        "to_node_id": step_id,
    })
    assert r3.success, f"add_connection failed: {r3.error}"

    # Verify orchestrator in-memory state
    mem_edges = orchestrator.workflow["edges"]
    assert len(mem_edges) == 1, f"Expected 1 edge in memory, got {len(mem_edges)}"
    assert mem_edges[0]["from"] == start_id
    assert mem_edges[0]["to"] == step_id

    # Verify DB state matches
    db_state = _load_db_workflow(store, wf_id, user_id)
    assert len(db_state["edges"]) == 1, f"Expected 1 edge in DB, got {len(db_state['edges'])}"
    assert db_state["edges"][0]["from"] == start_id
    assert db_state["edges"][0]["to"] == step_id


def test_sequential_tools_accumulate():
    """Adding 3 nodes sequentially: after each, count must be correct in memory and DB."""
    orchestrator, store, wf_id, user_id = _make_orchestrator_and_workflow()

    labels = ["Alpha", "Beta", "Gamma"]

    for i, label in enumerate(labels, start=1):
        result = orchestrator.run_tool("add_node", {
            "type": "process",
            "label": label,
            "x": i * 100,
            "y": 0,
        })
        assert result.success, f"add_node '{label}' failed: {result.error}"

        # Check in-memory count after each addition
        mem_count = len(orchestrator.workflow["nodes"])
        assert mem_count == i, (
            f"After adding '{label}': expected {i} nodes in memory, got {mem_count}"
        )

        # Check DB count after each addition
        db_state = _load_db_workflow(store, wf_id, user_id)
        db_count = len(db_state["nodes"])
        assert db_count == i, (
            f"After adding '{label}': expected {i} nodes in DB, got {db_count}"
        )

    # Final verification: all labels present in both places
    mem_labels = {n["label"] for n in orchestrator.workflow["nodes"]}
    db_state = _load_db_workflow(store, wf_id, user_id)
    db_labels = {n["label"] for n in db_state["nodes"]}
    assert mem_labels == set(labels), f"Memory labels mismatch: {mem_labels}"
    assert db_labels == set(labels), f"DB labels mismatch: {db_labels}"


def test_delete_node_syncs():
    """After adding then deleting a node, it must be gone from both memory and DB."""
    orchestrator, store, wf_id, user_id = _make_orchestrator_and_workflow()

    # Add a node
    r1 = orchestrator.run_tool("add_node", {
        "type": "process",
        "label": "To Be Deleted",
        "x": 0,
        "y": 0,
    })
    assert r1.success, f"add_node failed: {r1.error}"

    # Confirm it exists
    assert len(orchestrator.workflow["nodes"]) == 1
    node_id = orchestrator.workflow["nodes"][0]["id"]

    # Delete the node
    r2 = orchestrator.run_tool("delete_node", {"node_id": node_id})
    assert r2.success, f"delete_node failed: {r2.error}"

    # Verify it's gone from memory
    assert len(orchestrator.workflow["nodes"]) == 0, (
        f"Expected 0 nodes in memory after delete, got {len(orchestrator.workflow['nodes'])}"
    )

    # Verify it's gone from DB
    db_state = _load_db_workflow(store, wf_id, user_id)
    assert len(db_state["nodes"]) == 0, (
        f"Expected 0 nodes in DB after delete, got {len(db_state['nodes'])}"
    )
