"""Integration tests: verify session_state passed to tools has the correct structure.

These tests monkey-patch a tool's execute() method to capture the session_state
kwarg, then call orchestrator.run_tool() and verify the shape and types of
the session_state dict. This ensures the contract between orchestrator and
tools is maintained.

Phase 0 safety net: captures the current session_state shape before refactoring.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

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

    tmp_dir = tempfile.mkdtemp(prefix="lemon_session_shape_test_")
    db_path = Path(tmp_dir) / "test.sqlite"
    workflow_store = WorkflowStore(db_path)

    workflow_id = "wf_session_shape_test"
    user_id = "test_user"

    # Create an empty workflow in the database
    workflow_store.create_workflow(
        workflow_id=workflow_id,
        user_id=user_id,
        name="Session Shape Test",
        description="",
    )

    # Wire up orchestrator to the DB-backed workflow
    orchestrator.workflow_store = workflow_store
    orchestrator.user_id = user_id
    orchestrator.current_workflow_id = workflow_id
    orchestrator.current_workflow_name = "Session Shape Test"
    orchestrator.repo_root = PROJECT_ROOT

    return orchestrator, workflow_store, workflow_id, user_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_session_state_has_current_workflow():
    """session_state['current_workflow'] must have 'nodes' and 'edges' keys."""
    orchestrator, store, wf_id, user_id = _make_orchestrator_and_workflow()

    # Capture session_state by monkey-patching add_node's execute
    captured: Dict[str, Any] = {}
    original_execute = orchestrator.tools._tools["add_node"].execute

    def patched_execute(args, **kwargs):
        # Capture the session_state kwarg before delegating to the real method
        captured["session_state"] = kwargs.get("session_state", {})
        return original_execute(args, **kwargs)

    orchestrator.tools._tools["add_node"].execute = patched_execute

    try:
        result = orchestrator.run_tool("add_node", {
            "type": "process",
            "label": "Shape Test Node",
            "x": 0,
            "y": 0,
        })
        assert result.success, f"add_node failed: {result.error}"
    finally:
        # Restore original execute to avoid test pollution
        orchestrator.tools._tools["add_node"].execute = original_execute

    # Verify session_state was captured
    assert "session_state" in captured, "session_state was not passed to tool"
    ss = captured["session_state"]

    # current_workflow must exist with nodes and edges keys
    assert "current_workflow" in ss, "session_state missing 'current_workflow'"
    cw = ss["current_workflow"]
    assert isinstance(cw, dict), f"current_workflow is not a dict: {type(cw)}"
    assert "nodes" in cw, "current_workflow missing 'nodes' key"
    assert "edges" in cw, "current_workflow missing 'edges' key"
    assert isinstance(cw["nodes"], list), f"current_workflow['nodes'] is not a list: {type(cw['nodes'])}"
    assert isinstance(cw["edges"], list), f"current_workflow['edges'] is not a list: {type(cw['edges'])}"


def test_session_state_has_workflow_analysis():
    """session_state['workflow_analysis'] must have 'variables' and 'outputs' keys."""
    orchestrator, store, wf_id, user_id = _make_orchestrator_and_workflow()

    captured: Dict[str, Any] = {}
    original_execute = orchestrator.tools._tools["add_node"].execute

    def patched_execute(args, **kwargs):
        captured["session_state"] = kwargs.get("session_state", {})
        return original_execute(args, **kwargs)

    orchestrator.tools._tools["add_node"].execute = patched_execute

    try:
        result = orchestrator.run_tool("add_node", {
            "type": "process",
            "label": "Analysis Test Node",
            "x": 0,
            "y": 0,
        })
        assert result.success, f"add_node failed: {result.error}"
    finally:
        orchestrator.tools._tools["add_node"].execute = original_execute

    ss = captured["session_state"]

    # workflow_analysis must exist with variables and outputs keys
    assert "workflow_analysis" in ss, "session_state missing 'workflow_analysis'"
    wa = ss["workflow_analysis"]
    assert isinstance(wa, dict), f"workflow_analysis is not a dict: {type(wa)}"
    assert "variables" in wa, "workflow_analysis missing 'variables' key"
    assert "outputs" in wa, "workflow_analysis missing 'outputs' key"
    assert isinstance(wa["variables"], list), f"workflow_analysis['variables'] is not a list"
    assert isinstance(wa["outputs"], list), f"workflow_analysis['outputs'] is not a list"


def test_session_state_has_workflow_store():
    """session_state['workflow_store'] must be a WorkflowStore instance."""
    orchestrator, store, wf_id, user_id = _make_orchestrator_and_workflow()

    captured: Dict[str, Any] = {}
    original_execute = orchestrator.tools._tools["add_node"].execute

    def patched_execute(args, **kwargs):
        captured["session_state"] = kwargs.get("session_state", {})
        return original_execute(args, **kwargs)

    orchestrator.tools._tools["add_node"].execute = patched_execute

    try:
        result = orchestrator.run_tool("add_node", {
            "type": "process",
            "label": "Store Test Node",
            "x": 0,
            "y": 0,
        })
        assert result.success, f"add_node failed: {result.error}"
    finally:
        orchestrator.tools._tools["add_node"].execute = original_execute

    ss = captured["session_state"]

    # workflow_store must be present and be a WorkflowStore instance
    assert "workflow_store" in ss, "session_state missing 'workflow_store'"
    assert isinstance(ss["workflow_store"], WorkflowStore), (
        f"workflow_store is not a WorkflowStore: {type(ss['workflow_store'])}"
    )


def test_session_state_has_user_id():
    """session_state['user_id'] must be a string matching the orchestrator's user_id."""
    orchestrator, store, wf_id, user_id = _make_orchestrator_and_workflow()

    captured: Dict[str, Any] = {}
    original_execute = orchestrator.tools._tools["add_node"].execute

    def patched_execute(args, **kwargs):
        captured["session_state"] = kwargs.get("session_state", {})
        return original_execute(args, **kwargs)

    orchestrator.tools._tools["add_node"].execute = patched_execute

    try:
        result = orchestrator.run_tool("add_node", {
            "type": "process",
            "label": "User ID Test Node",
            "x": 0,
            "y": 0,
        })
        assert result.success, f"add_node failed: {result.error}"
    finally:
        orchestrator.tools._tools["add_node"].execute = original_execute

    ss = captured["session_state"]

    # user_id must be present and be a string
    assert "user_id" in ss, "session_state missing 'user_id'"
    assert isinstance(ss["user_id"], str), f"user_id is not a string: {type(ss['user_id'])}"
    assert ss["user_id"] == user_id, (
        f"user_id mismatch: expected '{user_id}', got '{ss['user_id']}'"
    )


def test_session_state_has_current_workflow_id():
    """session_state['current_workflow_id'] must match the orchestrator's workflow ID."""
    orchestrator, store, wf_id, user_id = _make_orchestrator_and_workflow()

    captured: Dict[str, Any] = {}
    original_execute = orchestrator.tools._tools["add_node"].execute

    def patched_execute(args, **kwargs):
        captured["session_state"] = kwargs.get("session_state", {})
        return original_execute(args, **kwargs)

    orchestrator.tools._tools["add_node"].execute = patched_execute

    try:
        result = orchestrator.run_tool("add_node", {
            "type": "process",
            "label": "WF ID Test Node",
            "x": 0,
            "y": 0,
        })
        assert result.success, f"add_node failed: {result.error}"
    finally:
        orchestrator.tools._tools["add_node"].execute = original_execute

    ss = captured["session_state"]

    # current_workflow_id must be present and match the workflow ID
    assert "current_workflow_id" in ss, "session_state missing 'current_workflow_id'"
    assert ss["current_workflow_id"] == wf_id, (
        f"current_workflow_id mismatch: expected '{wf_id}', got '{ss['current_workflow_id']}'"
    )


def test_session_state_full_shape():
    """Verify all expected keys exist in a single session_state capture.

    This is a comprehensive check that all required keys are present at once,
    complementing the individual tests above.
    """
    orchestrator, store, wf_id, user_id = _make_orchestrator_and_workflow()

    captured: Dict[str, Any] = {}
    original_execute = orchestrator.tools._tools["add_node"].execute

    def patched_execute(args, **kwargs):
        captured["session_state"] = kwargs.get("session_state", {})
        return original_execute(args, **kwargs)

    orchestrator.tools._tools["add_node"].execute = patched_execute

    try:
        result = orchestrator.run_tool("add_node", {
            "type": "process",
            "label": "Full Shape Test",
            "x": 0,
            "y": 0,
        })
        assert result.success, f"add_node failed: {result.error}"
    finally:
        orchestrator.tools._tools["add_node"].execute = original_execute

    ss = captured["session_state"]

    # All required keys must be present
    required_keys = [
        "current_workflow",
        "workflow_analysis",
        "current_workflow_id",
        "workflow_store",
        "user_id",
    ]
    for key in required_keys:
        assert key in ss, f"session_state missing required key: '{key}'"

    # Type checks on all keys
    assert isinstance(ss["current_workflow"], dict)
    assert isinstance(ss["workflow_analysis"], dict)
    assert isinstance(ss["current_workflow_id"], str)
    assert isinstance(ss["workflow_store"], WorkflowStore)
    assert isinstance(ss["user_id"], str)

    # Nested structure checks
    assert "nodes" in ss["current_workflow"]
    assert "edges" in ss["current_workflow"]
    assert "variables" in ss["workflow_analysis"]
    assert "outputs" in ss["workflow_analysis"]
