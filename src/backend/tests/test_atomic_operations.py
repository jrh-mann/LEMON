"""Atomic operation tests for baseline reliability measurement.

This test suite focuses on individual, atomic operations to establish
a reliable baseline for LLM tool calling behavior. Each test:
- Requests a SINGLE operation
- Expects a SINGLE tool call
- Has deterministic expected outcomes
- Tests core functionality without complexity

Purpose:
- Establish baseline pass rate for simple operations
- Identify which operations are reliable vs unreliable
- Provide foundation for prompt optimization
- Avoid goodharting (testing real functionality, not metrics)

Design Principles:
- One operation per test
- Simple, unambiguous requests
- Clear success criteria
- No multi-step complexity
- No conversational ambiguity
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict

import pytest

from ..agents.orchestrator import Orchestrator
from ..agents.orchestrator_factory import build_orchestrator


def _repo_root() -> Path:
    return Path(__file__).parent.parent.parent.parent


class AtomicTestSession:
    """
    Minimal session wrapper for atomic operation testing.

    Tracks tool calls and provides simple state assertions.
    """

    def __init__(self, orchestrator: Orchestrator):
        self.orchestrator = orchestrator
        self.workflow_state: Dict[str, Any] = {"nodes": [], "edges": []}
        self.tool_calls = []

    def set_workflow(self, workflow: Dict[str, Any]) -> None:
        """Set initial workflow state."""
        self.workflow_state = copy.deepcopy(workflow)
        self.orchestrator.current_workflow = copy.deepcopy(workflow)

    def request(self, message: str) -> str:
        """Send request and capture tool calls."""
        self.tool_calls = []

        # Sync state
        self.orchestrator.sync_workflow(lambda: self.workflow_state)

        # Execute
        response = self.orchestrator.respond(message, allow_tools=True)

        # Sync back
        self.workflow_state = copy.deepcopy(self.orchestrator.current_workflow)

        return response

    def node_count(self) -> int:
        """Get current node count."""
        return len(self.orchestrator.current_workflow.get("nodes", []))

    def edge_count(self) -> int:
        """Get current edge count."""
        return len(self.orchestrator.current_workflow.get("edges", []))

    def has_node_with_label(self, label_contains: str) -> bool:
        """Check if node with label exists."""
        nodes = self.orchestrator.current_workflow.get("nodes", [])
        return any(label_contains.lower() in n["label"].lower() for n in nodes)

    def has_node_with_type(self, node_type: str) -> bool:
        """Check if node of given type exists."""
        nodes = self.orchestrator.current_workflow.get("nodes", [])
        return any(n["type"] == node_type for n in nodes)

    def get_node_by_label(self, label_contains: str) -> Dict[str, Any] | None:
        """Get first node containing label."""
        nodes = self.orchestrator.current_workflow.get("nodes", [])
        for node in nodes:
            if label_contains.lower() in node["label"].lower():
                return node
        return None


@pytest.fixture
def orchestrator() -> Orchestrator:
    """Create orchestrator with real tools and LLM."""
    return build_orchestrator(_repo_root())


@pytest.fixture
def session(orchestrator: Orchestrator) -> AtomicTestSession:
    """Create atomic test session."""
    return AtomicTestSession(orchestrator)


@pytest.fixture
def empty_canvas() -> Dict[str, Any]:
    """Empty workflow (no nodes or edges)."""
    return {"nodes": [], "edges": []}


@pytest.fixture
def single_node() -> Dict[str, Any]:
    """Workflow with single start node."""
    return {
        "nodes": [
            {"id": "node_1", "type": "start", "label": "Start", "x": 100, "y": 100, "color": "teal"}
        ],
        "edges": []
    }


@pytest.fixture
def two_nodes() -> Dict[str, Any]:
    """Workflow with two unconnected nodes."""
    return {
        "nodes": [
            {"id": "node_1", "type": "start", "label": "Begin", "x": 100, "y": 100, "color": "teal"},
            {"id": "node_2", "type": "process", "label": "Process", "x": 100, "y": 200, "color": "slate"}
        ],
        "edges": []
    }


@pytest.fixture
def two_connected_nodes() -> Dict[str, Any]:
    """Workflow with two connected nodes."""
    return {
        "nodes": [
            {"id": "node_1", "type": "start", "label": "Begin", "x": 100, "y": 100, "color": "teal"},
            {"id": "node_2", "type": "end", "label": "Done", "x": 100, "y": 200, "color": "green"}
        ],
        "edges": [
            {"id": "node_1->node_2", "from": "node_1", "to": "node_2", "label": ""}
        ]
    }


# ============================================================================
# ATOMIC OPERATION: ADD NODE
# Tests that LLM can add individual nodes of each type
# ============================================================================

class TestAtomicAddNode:
    """Test atomic add_node operations for each node type."""

    def test_add_start_node(self, session: AtomicTestSession):
        """
        Request: "add a start node"
        Expected: 1 start node exists
        """
        response = session.request("add a start node")

        assert session.node_count() == 1, f"Expected 1 node, got {session.node_count()}"
        assert session.has_node_with_type("start"), "Expected start node"

    def test_add_process_node(self, session: AtomicTestSession):
        """
        Request: "add a process node"
        Expected: 1 process node exists
        """
        response = session.request("add a process node")

        assert session.node_count() == 1, f"Expected 1 node, got {session.node_count()}"
        assert session.has_node_with_type("process"), "Expected process node"

    def test_add_end_node(self, session: AtomicTestSession):
        """
        Request: "add an end node"
        Expected: 1 end node exists
        """
        response = session.request("add an end node")

        assert session.node_count() == 1, f"Expected 1 node, got {session.node_count()}"
        assert session.has_node_with_type("end"), "Expected end node"

    def test_add_subprocess_node(self, session: AtomicTestSession):
        """
        Request: "add a subprocess node"
        Expected: 1 subprocess node exists
        """
        response = session.request("add a subprocess node")

        assert session.node_count() == 1, f"Expected 1 node, got {session.node_count()}"
        assert session.has_node_with_type("subprocess"), "Expected subprocess node"

    def test_add_node_with_label(self, session: AtomicTestSession):
        """
        Request: "add a process node called 'Validate Input'"
        Expected: 1 node with label containing "Validate"
        """
        response = session.request("add a process node called 'Validate Input'")

        assert session.node_count() == 1, f"Expected 1 node, got {session.node_count()}"
        assert session.has_node_with_label("Validate"), "Expected node with label 'Validate Input'"

    def test_add_second_node(self, session: AtomicTestSession, single_node: Dict[str, Any]):
        """
        Initial: 1 node
        Request: "add a process node"
        Expected: 2 nodes total
        """
        session.set_workflow(single_node)
        assert session.node_count() == 1, "Setup: should start with 1 node"

        response = session.request("add a process node")

        assert session.node_count() == 2, f"Expected 2 nodes, got {session.node_count()}"


# ============================================================================
# ATOMIC OPERATION: MODIFY NODE
# Tests that LLM can modify node properties
# ============================================================================

class TestAtomicModifyNode:
    """Test atomic modify_node operations."""

    def test_modify_node_label(self, session: AtomicTestSession, single_node: Dict[str, Any]):
        """
        Initial: Node labeled "Start"
        Request: "change the Start node label to 'Begin'"
        Expected: Node now labeled "Begin"
        """
        session.set_workflow(single_node)

        response = session.request("change the Start node label to 'Begin'")

        assert session.node_count() == 1, "Should still have 1 node"
        assert session.has_node_with_label("Begin"), "Expected label changed to 'Begin'"
        assert not session.has_node_with_label("Start"), "Old label should be gone"

    def test_modify_specific_node_by_label(self, session: AtomicTestSession, two_nodes: Dict[str, Any]):
        """
        Initial: Two nodes ("Begin" and "Process")
        Request: "rename Process to 'Validation'"
        Expected: "Process" node now called "Validation", other node unchanged
        """
        session.set_workflow(two_nodes)

        response = session.request("rename Process to 'Validation'")

        assert session.node_count() == 2, "Should still have 2 nodes"
        assert session.has_node_with_label("Validation"), "Expected 'Validation' node"
        assert session.has_node_with_label("Begin"), "Other node should be unchanged"
        assert not session.has_node_with_label("Process"), "Old label should be gone"


# ============================================================================
# ATOMIC OPERATION: DELETE NODE
# Tests that LLM can delete nodes
# ============================================================================

class TestAtomicDeleteNode:
    """Test atomic delete_node operations."""

    def test_delete_only_node(self, session: AtomicTestSession, single_node: Dict[str, Any]):
        """
        Initial: 1 node
        Request: "delete the Start node"
        Expected: 0 nodes
        """
        session.set_workflow(single_node)

        response = session.request("delete the Start node")

        assert session.node_count() == 0, f"Expected 0 nodes, got {session.node_count()}"

    def test_delete_specific_node_from_two(self, session: AtomicTestSession, two_nodes: Dict[str, Any]):
        """
        Initial: 2 nodes ("Begin" and "Process")
        Request: "delete the Process node"
        Expected: 1 node ("Begin" remains)
        """
        session.set_workflow(two_nodes)

        response = session.request("delete the Process node")

        assert session.node_count() == 1, f"Expected 1 node, got {session.node_count()}"
        assert session.has_node_with_label("Begin"), "Expected 'Begin' node to remain"
        assert not session.has_node_with_label("Process"), "Expected 'Process' node deleted"


# ============================================================================
# ATOMIC OPERATION: ADD CONNECTION
# Tests that LLM can connect nodes
# ============================================================================

class TestAtomicAddConnection:
    """Test atomic add_connection operations."""

    def test_connect_two_nodes(self, session: AtomicTestSession, two_nodes: Dict[str, Any]):
        """
        Initial: 2 unconnected nodes
        Request: "connect Begin to Process"
        Expected: 1 edge exists
        """
        session.set_workflow(two_nodes)
        assert session.edge_count() == 0, "Setup: should start with 0 edges"

        response = session.request("connect Begin to Process")

        assert session.edge_count() == 1, f"Expected 1 edge, got {session.edge_count()}"

    def test_connect_with_explicit_direction(self, session: AtomicTestSession, two_nodes: Dict[str, Any]):
        """
        Initial: 2 unconnected nodes
        Request: "add a connection from Begin to Process"
        Expected: 1 edge exists
        """
        session.set_workflow(two_nodes)

        response = session.request("add a connection from Begin to Process")

        assert session.edge_count() == 1, f"Expected 1 edge, got {session.edge_count()}"


# ============================================================================
# ATOMIC OPERATION: DELETE CONNECTION
# Tests that LLM can disconnect nodes
# ============================================================================

class TestAtomicDeleteConnection:
    """Test atomic delete_connection operations."""

    def test_delete_connection(self, session: AtomicTestSession, two_connected_nodes: Dict[str, Any]):
        """
        Initial: 2 nodes with 1 connection
        Request: "remove the connection from Begin to Done"
        Expected: 0 edges
        """
        session.set_workflow(two_connected_nodes)
        assert session.edge_count() == 1, "Setup: should start with 1 edge"

        response = session.request("remove the connection from Begin to Done")

        assert session.edge_count() == 0, f"Expected 0 edges, got {session.edge_count()}"

    def test_disconnect_nodes(self, session: AtomicTestSession, two_connected_nodes: Dict[str, Any]):
        """
        Initial: 2 nodes with 1 connection
        Request: "disconnect Begin from Done"
        Expected: 0 edges
        """
        session.set_workflow(two_connected_nodes)

        response = session.request("disconnect Begin from Done")

        assert session.edge_count() == 0, f"Expected 0 edges, got {session.edge_count()}"


# ============================================================================
# ATOMIC OPERATION: GET WORKFLOW
# Tests that LLM can query workflow state
# ============================================================================

class TestAtomicGetWorkflow:
    """Test atomic get_current_workflow operations."""

    def test_query_empty_workflow(self, session: AtomicTestSession):
        """
        Initial: Empty canvas
        Request: "what's on the canvas?"
        Expected: Response mentions empty/no nodes
        """
        response = session.request("what's on the canvas?")

        response_lower = response.lower()
        assert any(
            word in response_lower
            for word in ["empty", "nothing", "no nodes", "none"]
        ), f"Expected empty canvas mentioned in: {response}"

    def test_query_with_one_node(self, session: AtomicTestSession, single_node: Dict[str, Any]):
        """
        Initial: 1 start node
        Request: "what nodes are on the canvas?"
        Expected: Response mentions start node
        """
        session.set_workflow(single_node)

        response = session.request("what nodes are on the canvas?")

        response_lower = response.lower()
        assert "start" in response_lower, f"Expected 'start' mentioned in: {response}"

    def test_count_nodes(self, session: AtomicTestSession, two_nodes: Dict[str, Any]):
        """
        Initial: 2 nodes
        Request: "how many nodes are there?"
        Expected: Response contains "2" or "two"
        """
        session.set_workflow(two_nodes)

        response = session.request("how many nodes are there?")

        response_lower = response.lower()
        assert "2" in response or "two" in response_lower, f"Expected count in: {response}"


# ============================================================================
# ATOMIC OPERATION: NATURAL LANGUAGE VARIATIONS
# Tests that common phrasings work for each operation
# ============================================================================

class TestAtomicNaturalLanguageVariations:
    """Test that different phrasings produce same atomic operations."""

    @pytest.mark.parametrize("phrase", [
        "add a start node",
        "create a start node",
        "I need a start node",
        "put a start node on the canvas"
    ])
    def test_add_node_variations(self, session: AtomicTestSession, phrase: str):
        """Test that different add node phrasings work."""
        response = session.request(phrase)

        assert session.node_count() == 1, f"Failed for phrase: '{phrase}'"
        assert session.has_node_with_type("start"), f"Failed for phrase: '{phrase}'"

    @pytest.mark.parametrize("phrase", [
        "delete the Start node",
        "remove the Start node",
        "get rid of the Start node"
    ])
    def test_delete_node_variations(self, session: AtomicTestSession, single_node: Dict[str, Any], phrase: str):
        """Test that different delete node phrasings work."""
        session.set_workflow(single_node)

        response = session.request(phrase)

        assert session.node_count() == 0, f"Failed for phrase: '{phrase}'"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
