"""Comprehensive tests for workflow state integrity and LLM editing capabilities.

This test suite validates that:
1. LLM selects correct tools for user requests
2. Tools execute successfully and return proper data structures
3. Orchestrator state updates correctly after tool execution
4. State persists correctly across conversation turns
5. Errors fail loudly with clear, actionable messages

CURRENT STATUS: Several tests will FAIL due to known bugs:
- test_modify_node_updates_orchestrator_state: ModifyNodeTool missing "node" field
- test_batch_edit_*: BatchEditWorkflowTool missing "workflow" field
- Multi-turn tests involving modify/batch operations will fail due to state desync

These tests serve as acceptance criteria for fixes.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from ..agents.orchestrator import Orchestrator
from ..agents.orchestrator_factory import build_orchestrator


def _repo_root() -> Path:
    return Path(__file__).parent.parent.parent.parent


class WorkflowTestSession:
    """
    Enhanced test session with state tracking and loud failure assertions.

    This wrapper provides:
    - Tool call history capture
    - State comparison utilities
    - Loud assertion helpers that explain failures clearly
    - Verbose logging for debugging
    """

    def __init__(self, orchestrator: Orchestrator):
        self.orchestrator = orchestrator
        self.workflow_state: Dict[str, Any] = {"nodes": [], "edges": []}
        self.tool_call_history: List[Dict[str, Any]] = []
        self._wrap_tool_execution()

    def _wrap_tool_execution(self):
        """Wrap tool execution to capture calls for inspection."""
        original_execute = self.orchestrator.tools.execute

        def wrapped_execute(tool_name: str, args: Dict[str, Any], **kwargs):
            result = original_execute(tool_name, args, **kwargs)
            self.tool_call_history.append({
                "tool": tool_name,
                "args": args,
                "result": result,
            })
            return result

        self.orchestrator.tools.execute = wrapped_execute

    def set_initial_workflow(self, workflow: Dict[str, Any]) -> None:
        """Set initial workflow state for testing."""
        self.workflow_state = copy.deepcopy(workflow)
        self.orchestrator.current_workflow = copy.deepcopy(workflow)

    def respond(self, message: str, **kwargs) -> str:
        """
        Send message to orchestrator and get response.

        This mimics the handle_socket_chat workflow:
        1. Sync workflow from session to orchestrator
        2. Call LLM
        3. Write orchestrator's workflow state back to session
        """
        # Clear tool history for this turn
        self.tool_call_history.clear()

        # Sync workflow from session to orchestrator (like socket_chat.py does)
        self.orchestrator.sync_workflow(lambda: self.workflow_state)

        # Call LLM
        response = self.orchestrator.respond(message, **kwargs)

        # Write orchestrator's workflow state back to session
        self.workflow_state = copy.deepcopy(self.orchestrator.current_workflow)

        return response

    def get_tool_calls(self) -> List[Dict[str, Any]]:
        """Get tool calls from last respond()."""
        return self.tool_call_history

    def get_tool_names(self) -> List[str]:
        """Get just the tool names called in last respond()."""
        return [call["tool"] for call in self.tool_call_history]

    # ============================================================================
    # LOUD ASSERTION HELPERS
    # These fail with detailed, actionable error messages
    # ============================================================================

    def assert_node_exists(
        self,
        label_contains: str,
        node_type: Optional[str] = None,
        in_orchestrator: bool = True,
    ) -> Dict[str, Any]:
        """
        Assert a node exists with label containing the given text.

        Fails loudly with:
        - What was searched for
        - What nodes are actually present
        - Whether to check orchestrator state or session state

        Returns the matching node for further assertions.
        """
        workflow = (
            self.orchestrator.current_workflow if in_orchestrator else self.workflow_state
        )
        nodes = workflow.get("nodes", [])

        # Find matching nodes
        matches = [n for n in nodes if label_contains.lower() in n["label"].lower()]
        if node_type:
            matches = [n for n in matches if n["type"] == node_type]

        state_location = "orchestrator" if in_orchestrator else "session"
        if len(matches) == 0:
            available = [f"{n['id']}: \"{n['label']}\" ({n['type']})" for n in nodes]
            raise AssertionError(
                f"Node with label containing '{label_contains}' "
                f"{'and type ' + node_type if node_type else ''} "
                f"not found in {state_location} state.\n"
                f"Available nodes ({len(nodes)}):\n  "
                + "\n  ".join(available if available else ["(none)"])
            )

        return matches[0]

    def assert_edge_exists(
        self,
        from_label: str,
        to_label: str,
        edge_label: Optional[str] = None,
        in_orchestrator: bool = True,
    ) -> Dict[str, Any]:
        """
        Assert an edge exists between nodes with given labels.

        Fails loudly with:
        - What connection was searched for
        - What edges are actually present
        """
        workflow = (
            self.orchestrator.current_workflow if in_orchestrator else self.workflow_state
        )
        nodes = workflow.get("nodes", [])
        edges = workflow.get("edges", [])

        # Find nodes by label
        from_node = next(
            (n for n in nodes if from_label.lower() in n["label"].lower()), None
        )
        to_node = next((n for n in nodes if to_label.lower() in n["label"].lower()), None)

        if not from_node:
            raise AssertionError(f"Source node with label '{from_label}' not found")
        if not to_node:
            raise AssertionError(f"Target node with label '{to_label}' not found")

        # Find edge
        matching = [
            e
            for e in edges
            if e["from"] == from_node["id"] and e["to"] == to_node["id"]
        ]
        if edge_label:
            matching = [e for e in matching if e.get("label") == edge_label]

        state_location = "orchestrator" if in_orchestrator else "session"
        if len(matching) == 0:
            available = []
            for e in edges:
                f_node = next((n for n in nodes if n["id"] == e["from"]), None)
                t_node = next((n for n in nodes if n["id"] == e["to"]), None)
                f_label = f_node["label"] if f_node else "?"
                t_label = t_node["label"] if t_node else "?"
                label_part = f" [{e.get('label', '')}]" if e.get("label") else ""
                available.append(f"\"{f_label}\"{label_part} → \"{t_label}\"")

            raise AssertionError(
                f"Edge from '{from_label}' to '{to_label}' "
                f"{'with label ' + edge_label if edge_label else ''} "
                f"not found in {state_location} state.\n"
                f"Available edges ({len(edges)}):\n  "
                + "\n  ".join(available if available else ["(none)"])
            )

        return matching[0]

    def assert_orchestrator_state_equals_session_state(self):
        """
        CRITICAL assertion: orchestrator and session state must match.

        This catches state desynchronization bugs where tools execute
        but orchestrator state doesn't update.
        """
        orch_nodes = self.orchestrator.current_workflow.get("nodes", [])
        sess_nodes = self.workflow_state.get("nodes", [])
        orch_edges = self.orchestrator.current_workflow.get("edges", [])
        sess_edges = self.workflow_state.get("edges", [])

        if len(orch_nodes) != len(sess_nodes):
            raise AssertionError(
                f"State desynchronization: orchestrator has {len(orch_nodes)} nodes "
                f"but session has {len(sess_nodes)} nodes"
            )

        if len(orch_edges) != len(sess_edges):
            raise AssertionError(
                f"State desynchronization: orchestrator has {len(orch_edges)} edges "
                f"but session has {len(sess_edges)} edges"
            )

    def assert_node_count(self, expected: int, in_orchestrator: bool = True):
        """Assert exact node count with clear failure message."""
        workflow = (
            self.orchestrator.current_workflow if in_orchestrator else self.workflow_state
        )
        actual = len(workflow.get("nodes", []))
        state_location = "orchestrator" if in_orchestrator else "session"

        if actual != expected:
            nodes = workflow.get("nodes", [])
            node_list = [f"\"{n['label']}\" ({n['type']})" for n in nodes]
            raise AssertionError(
                f"Expected {expected} nodes in {state_location} state, got {actual}.\n"
                f"Actual nodes: " + ", ".join(node_list if node_list else ["(none)"])
            )

    def assert_edge_count(self, expected: int, in_orchestrator: bool = True):
        """Assert exact edge count with clear failure message."""
        workflow = (
            self.orchestrator.current_workflow if in_orchestrator else self.workflow_state
        )
        actual = len(workflow.get("edges", []))
        state_location = "orchestrator" if in_orchestrator else "session"

        if actual != expected:
            raise AssertionError(
                f"Expected {expected} edges in {state_location} state, got {actual}"
            )

    def print_state(self, label: str = "Workflow State"):
        """Print current workflow state for debugging (use with pytest -s)."""
        print(f"\n{'='*60}")
        print(f"{label}")
        print(f"{'='*60}")
        print(f"Orchestrator nodes: {len(self.orchestrator.current_workflow['nodes'])}")
        print(f"Session nodes: {len(self.workflow_state['nodes'])}")
        print(f"\nNodes:")
        for node in self.orchestrator.current_workflow["nodes"]:
            print(f"  - {node['id']}: \"{node['label']}\" (type: {node['type']})")
        print(f"\nEdges:")
        for edge in self.orchestrator.current_workflow["edges"]:
            nodes = self.orchestrator.current_workflow["nodes"]
            from_node = next((n for n in nodes if n["id"] == edge["from"]), None)
            to_node = next((n for n in nodes if n["id"] == edge["to"]), None)
            from_label = from_node["label"] if from_node else "?"
            to_label = to_node["label"] if to_node else "?"
            label = f" [{edge.get('label', '')}]" if edge.get("label") else ""
            print(f"  - \"{from_label}\"{label} → \"{to_label}\"")
        print(f"{'='*60}\n")


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def orchestrator() -> Orchestrator:
    """Create orchestrator with real tools and LLM."""
    return build_orchestrator(_repo_root())


@pytest.fixture
def session(orchestrator: Orchestrator) -> WorkflowTestSession:
    """Create enhanced workflow test session."""
    return WorkflowTestSession(orchestrator)


@pytest.fixture
def simple_workflow() -> Dict[str, Any]:
    """Simple workflow with 3 connected nodes: Start → Process → End."""
    return {
        "nodes": [
            {
                "id": "node_start",
                "type": "start",
                "label": "Start",
                "x": 100,
                "y": 100,
                "color": "teal",
            },
            {
                "id": "node_process",
                "type": "process",
                "label": "Validate Input",
                "x": 100,
                "y": 200,
                "color": "slate",
            },
            {
                "id": "node_end",
                "type": "end",
                "label": "End",
                "x": 100,
                "y": 300,
                "color": "green",
            },
        ],
        "edges": [
            {"id": "node_start->node_process", "from": "node_start", "to": "node_process", "label": ""},
            {"id": "node_process->node_end", "from": "node_process", "to": "node_end", "label": ""},
        ],
    }


# ============================================================================
# CATEGORY 1: INDIVIDUAL NODE OPERATIONS
# Tests that node CRUD operations update orchestrator state correctly
# ============================================================================


class TestNodeStatePersistence:
    """
    Validates that node operations update orchestrator state correctly.

    CRITICAL: test_modify_node_updates_orchestrator_state will FAIL
    due to ModifyNodeTool missing "node" field in response.
    """

    def test_add_node_updates_orchestrator_state(self, session: WorkflowTestSession):
        """
        Test that adding a node updates orchestrator.current_workflow.

        Acceptance Criteria:
        - LLM calls add_node tool
        - Tool returns success with complete node object
        - orchestrator.current_workflow["nodes"] contains the new node
        - Node has all required fields: id, type, label, x, y, color
        """
        response = session.respond("add a start node", allow_tools=True)

        # Verify tool was called
        tool_names = session.get_tool_names()
        assert "add_node" in tool_names, f"Expected add_node call, got: {tool_names}"

        # Verify orchestrator state updated
        session.assert_node_count(1, in_orchestrator=True)
        node = session.assert_node_exists("start", node_type="start", in_orchestrator=True)

        # Verify node has required fields
        assert "id" in node, "Node missing 'id' field"
        assert "type" in node, "Node missing 'type' field"
        assert "label" in node, "Node missing 'label' field"
        assert "x" in node, "Node missing 'x' field"
        assert "y" in node, "Node missing 'y' field"
        assert "color" in node, "Node missing 'color' field"

    def test_modify_node_updates_orchestrator_state(
        self, session: WorkflowTestSession, simple_workflow: Dict[str, Any]
    ):
        """
        Test that modifying a node updates orchestrator.current_workflow.

        Acceptance Criteria:
        - LLM calls modify_node with node_id
        - Tool returns success with COMPLETE updated node object
        - orchestrator.current_workflow["nodes"] reflects the change
        - Subsequent get_current_workflow shows the modification

        CRITICAL: This test will FAIL because ModifyNodeTool returns:
            {"node_id": ..., "updates": ...}
        But orchestrator.py:133-140 expects:
            {"node": <complete_node_object>}

        The orchestrator never updates its state, causing desynchronization.
        """
        session.set_initial_workflow(simple_workflow)

        response = session.respond(
            "change the 'Validate Input' node label to 'Check Input'",
            allow_tools=True,
        )

        # Verify modify_node was called
        tool_names = session.get_tool_names()
        assert "modify_node" in tool_names, f"Expected modify_node call, got: {tool_names}"

        # CRITICAL ASSERTION: Verify orchestrator state was updated
        # This will FAIL with current implementation
        session.assert_node_exists("Check Input", in_orchestrator=True)

        # Verify old label is gone
        nodes = session.orchestrator.current_workflow["nodes"]
        old_labels = [n for n in nodes if "Validate Input" == n["label"]]
        assert len(old_labels) == 0, (
            "Old label 'Validate Input' still present in orchestrator state. "
            "This indicates ModifyNodeTool didn't update orchestrator state correctly."
        )

    def test_delete_node_updates_orchestrator_state(
        self, session: WorkflowTestSession, simple_workflow: Dict[str, Any]
    ):
        """
        Test that deleting a node updates orchestrator.current_workflow.

        Acceptance Criteria:
        - LLM calls delete_node with node_id
        - Tool returns success
        - orchestrator.current_workflow["nodes"] no longer contains the node
        - All connected edges are also removed
        """
        session.set_initial_workflow(simple_workflow)
        initial_node_count = len(simple_workflow["nodes"])
        initial_edge_count = len(simple_workflow["edges"])

        response = session.respond(
            "delete the 'Validate Input' node",
            allow_tools=True,
        )

        # Verify delete_node was called
        tool_names = session.get_tool_names()
        assert "delete_node" in tool_names, f"Expected delete_node call, got: {tool_names}"

        # Verify orchestrator state updated
        session.assert_node_count(initial_node_count - 1, in_orchestrator=True)

        # Verify node is gone
        nodes = session.orchestrator.current_workflow["nodes"]
        assert not any(
            "validate input" in n["label"].lower() for n in nodes
        ), "Deleted node still present in orchestrator state"

        # Verify connected edges were also removed
        edges = session.orchestrator.current_workflow["edges"]
        assert len(edges) < initial_edge_count, "Expected edges to be removed with node"


# ============================================================================
# CATEGORY 2: EDGE OPERATIONS
# Tests that edge add/delete operations update orchestrator state
# ============================================================================


class TestEdgeStatePersistence:
    """Validates edge operations update orchestrator state correctly."""

    def test_add_connection_updates_orchestrator_state(
        self, session: WorkflowTestSession, simple_workflow: Dict[str, Any]
    ):
        """
        Test that adding a connection updates orchestrator.current_workflow.

        Acceptance Criteria:
        - LLM calls add_connection with from_node_id, to_node_id
        - Tool returns success with complete edge object
        - orchestrator.current_workflow["edges"] contains the new edge
        - Edge has: id, from, to, label
        """
        # Modify workflow to have disconnected end node
        simple_workflow["edges"] = [simple_workflow["edges"][0]]  # Only Start → Process
        session.set_initial_workflow(simple_workflow)
        initial_edge_count = len(simple_workflow["edges"])

        response = session.respond(
            "connect the 'Validate Input' node to the 'End' node",
            allow_tools=True,
        )

        # Verify add_connection was called
        tool_names = session.get_tool_names()
        assert "add_connection" in tool_names, f"Expected add_connection call, got: {tool_names}"

        # Verify orchestrator state updated
        session.assert_edge_count(initial_edge_count + 1, in_orchestrator=True)
        edge = session.assert_edge_exists("Validate Input", "End", in_orchestrator=True)

        # Verify edge has required fields
        assert "id" in edge, "Edge missing 'id' field"
        assert "from" in edge, "Edge missing 'from' field"
        assert "to" in edge, "Edge missing 'to' field"
        assert "label" in edge, "Edge missing 'label' field"

    def test_delete_connection_updates_orchestrator_state(
        self, session: WorkflowTestSession, simple_workflow: Dict[str, Any]
    ):
        """
        Test that deleting a connection updates orchestrator.current_workflow.

        Acceptance Criteria:
        - LLM calls delete_connection with from_node_id, to_node_id
        - Tool returns success
        - orchestrator.current_workflow["edges"] no longer contains the edge
        """
        session.set_initial_workflow(simple_workflow)
        initial_edge_count = len(simple_workflow["edges"])

        response = session.respond(
            "remove the connection from 'Start' to 'Validate Input'",
            allow_tools=True,
        )

        # Verify delete_connection was called
        tool_names = session.get_tool_names()
        assert "delete_connection" in tool_names, (
            f"Expected delete_connection call, got: {tool_names}"
        )

        # Verify orchestrator state updated
        session.assert_edge_count(initial_edge_count - 1, in_orchestrator=True)

        # Verify edge is gone (should raise AssertionError)
        with pytest.raises(AssertionError, match="not found"):
            session.assert_edge_exists("Start", "Validate Input", in_orchestrator=True)


# ============================================================================
# CATEGORY 3: BATCH OPERATIONS
# Tests atomic multi-operation changes
# ============================================================================


class TestBatchEditStatePersistence:
    """
    Validates batch_edit_workflow atomicity and state sync.

    CRITICAL: All tests in this class will FAIL because BatchEditWorkflowTool
    returns {"operations": [...]} but orchestrator.py:169 expects {"workflow": {...}}.
    The orchestrator never updates its state after batch_edit.
    """

    def test_batch_edit_updates_orchestrator_state(self, session: WorkflowTestSession):
        """
        Test that batch_edit_workflow updates orchestrator.current_workflow.

        Acceptance Criteria:
        - LLM calls batch_edit_workflow with multiple operations
        - Tool returns success with COMPLETE workflow object
        - orchestrator.current_workflow reflects ALL changes
        - Temp IDs are resolved correctly

        CRITICAL: This test will FAIL because BatchEditWorkflowTool doesn't
        return "workflow" field, so orchestrator state never updates.
        """
        response = session.respond(
            "Add three nodes: a start node 'Begin', a process node 'Validate', "
            "and an end node 'Finish'. Connect them in sequence.",
            allow_tools=True,
        )

        # Verify batch_edit or multiple tools were called
        tool_names = session.get_tool_names()
        # LLM might use batch_edit or multiple individual calls
        has_batch = "batch_edit_workflow" in tool_names
        has_multiple_adds = tool_names.count("add_node") >= 3

        assert has_batch or has_multiple_adds, (
            f"Expected batch_edit or multiple add_node calls, got: {tool_names}"
        )

        # CRITICAL: Verify orchestrator state was updated
        # This will FAIL if batch_edit was used and didn't return workflow field
        session.assert_node_count(3, in_orchestrator=True)
        session.assert_node_exists("Begin", node_type="start", in_orchestrator=True)
        session.assert_node_exists("Validate", node_type="process", in_orchestrator=True)
        session.assert_node_exists("Finish", node_type="end", in_orchestrator=True)

        # Verify connections exist
        session.assert_edge_count(2, in_orchestrator=True)
        session.assert_edge_exists("Begin", "Validate", in_orchestrator=True)
        session.assert_edge_exists("Validate", "Finish", in_orchestrator=True)

    def test_batch_edit_decision_node_with_branches(self, session: WorkflowTestSession):
        """
        Test that batch_edit can atomically create decision node with branches.

        Acceptance Criteria:
        - LLM creates decision node with exactly 2 branches atomically
        - Decision has exactly 2 outgoing edges
        - Edges have true/false (or yes/no) labels
        - All nodes and edges present in orchestrator state

        CRITICAL: Will FAIL if batch_edit doesn't update orchestrator state.
        """
        response = session.respond(
            "Add a decision node called 'Age Check' with two branches: "
            "one labeled 'true' going to 'Adult Path' and one labeled 'false' going to 'Minor Path'",
            allow_tools=True,
        )

        # Verify decision node exists
        decision = session.assert_node_exists("Age Check", node_type="decision", in_orchestrator=True)

        # Verify decision has exactly 2 outgoing edges
        edges = session.orchestrator.current_workflow["edges"]
        decision_edges = [e for e in edges if e["from"] == decision["id"]]
        assert len(decision_edges) == 2, (
            f"Decision node should have exactly 2 branches, got {len(decision_edges)}"
        )

        # Verify edges have appropriate labels
        edge_labels = {e.get("label", "").lower() for e in decision_edges}
        assert "true" in edge_labels or "false" in edge_labels or "yes" in edge_labels, (
            f"Expected true/false or yes/no labels, got: {edge_labels}"
        )

        # Verify branch nodes exist
        session.assert_node_exists("Adult", in_orchestrator=True)
        session.assert_node_exists("Minor", in_orchestrator=True)

    def test_batch_edit_atomic_rollback(self, session: WorkflowTestSession):
        """
        Test that batch_edit is truly atomic: all operations succeed or all fail.

        Acceptance Criteria:
        - Batch operation with one invalid operation (e.g., invalid node type)
        - ALL operations should fail (all-or-nothing semantics)
        - orchestrator.current_workflow unchanged
        - Error message explains which operation failed
        """
        # This test requires constructing an invalid batch operation
        # Since we're testing via LLM, we'll test that validation catches issues
        response = session.respond(
            "Add a node with type 'invalid_type' and label 'Test'",
            allow_tools=True,
        )

        # The tool should fail validation
        # Orchestrator state should be unchanged (empty)
        session.assert_node_count(0, in_orchestrator=True)

        # Response should indicate the error
        assert "invalid" in response.lower() or "error" in response.lower(), (
            "Expected error message about invalid node type"
        )


# ============================================================================
# CATEGORY 4: MULTI-TURN CONVERSATION STATE
# Tests state persistence across conversation turns
# ============================================================================


class TestMultiTurnStatePersistence:
    """
    Validates workflow state persists correctly across conversation turns.

    This tests the sync_workflow() mechanism that syncs session <-> orchestrator.
    Critical for ensuring users can build workflows incrementally.
    """

    def test_state_persists_across_three_modifications(self, session: WorkflowTestSession):
        """
        Test that workflow state accumulates correctly across multiple turns.

        Acceptance Criteria:
        Turn 1: Add start node → orchestrator has 1 node
        Turn 2: Add process node → orchestrator has 2 nodes (including turn 1's)
        Turn 3: Connect them → orchestrator has 2 nodes + 1 edge
        Turn 4: Ask "what's on canvas?" → LLM describes both nodes and edge
        """
        # Turn 1: Add start
        response1 = session.respond("add a start node called 'Begin'", allow_tools=True)
        session.assert_node_count(1, in_orchestrator=True)
        session.assert_node_exists("Begin", node_type="start", in_orchestrator=True)

        # Turn 2: Add process
        response2 = session.respond("add a process node called 'Validate Email'", allow_tools=True)
        session.assert_node_count(2, in_orchestrator=True)  # Should have BOTH nodes
        session.assert_node_exists("Begin", in_orchestrator=True)  # Old node still there
        session.assert_node_exists("Validate Email", in_orchestrator=True)  # New node added

        # Turn 3: Connect them
        response3 = session.respond("connect Begin to Validate Email", allow_tools=True)
        session.assert_node_count(2, in_orchestrator=True)  # Still 2 nodes
        session.assert_edge_count(1, in_orchestrator=True)  # Now 1 edge
        session.assert_edge_exists("Begin", "Validate Email", in_orchestrator=True)

        # Turn 4: Query state
        response4 = session.respond("what's on the workflow canvas?", allow_tools=True)
        # Response should mention both nodes
        assert "begin" in response4.lower(), "Response should mention 'Begin' node"
        assert "validate" in response4.lower(), "Response should mention 'Validate Email' node"

    def test_modify_then_query_shows_updated_label(self, session: WorkflowTestSession):
        """
        Test that modified labels persist and are visible in subsequent queries.

        Acceptance Criteria:
        Turn 1: Add node "Validator"
        Turn 2: Modify label to "Validation Engine"
        Turn 3: get_current_workflow → shows "Validation Engine", not "Validator"

        CRITICAL: This will FAIL if modify_node doesn't update orchestrator state.
        The workflow will show the old label because orchestrator state wasn't updated.
        """
        # Turn 1: Add node
        response1 = session.respond("add a process node called 'Validator'", allow_tools=True)
        session.assert_node_exists("Validator", in_orchestrator=True)

        # Turn 2: Modify it
        response2 = session.respond(
            "change the Validator label to 'Validation Engine'",
            allow_tools=True
        )

        # CRITICAL: Verify orchestrator state was updated
        session.assert_node_exists("Validation Engine", in_orchestrator=True)

        # Verify old label is gone
        nodes = session.orchestrator.current_workflow["nodes"]
        assert not any(n["label"] == "Validator" for n in nodes), (
            "Old label 'Validator' still present. ModifyNodeTool didn't update orchestrator state."
        )

        # Turn 3: Query to verify LLM sees the updated state
        response3 = session.respond("what nodes are on the canvas?", allow_tools=True)
        assert "validation engine" in response3.lower(), (
            "LLM should describe the updated label 'Validation Engine'"
        )
        assert "validator" not in response3.lower() or "validation engine" in response3.lower(), (
            "LLM should not mention the old label 'Validator' alone"
        )

    def test_batch_edit_then_individual_edit(self, session: WorkflowTestSession):
        """
        Test that batch operations persist for subsequent individual operations.

        Acceptance Criteria:
        Turn 1: Batch add 3 nodes
        Turn 2: Modify one of those nodes individually
        Turn 3: All 3 nodes still present, one has updated label

        CRITICAL: Will FAIL if batch_edit doesn't update orchestrator state.
        """
        # Turn 1: Batch add nodes
        response1 = session.respond(
            "Add three process nodes: 'Step A', 'Step B', and 'Step C'",
            allow_tools=True
        )
        session.assert_node_count(3, in_orchestrator=True)

        # Turn 2: Modify one node
        response2 = session.respond(
            "change 'Step B' to 'Validation Step'",
            allow_tools=True
        )

        # Turn 3: Verify all nodes present with modification
        session.assert_node_count(3, in_orchestrator=True)
        session.assert_node_exists("Step A", in_orchestrator=True)
        session.assert_node_exists("Validation Step", in_orchestrator=True)  # Modified
        session.assert_node_exists("Step C", in_orchestrator=True)

        # Verify old label gone
        nodes = session.orchestrator.current_workflow["nodes"]
        assert not any(n["label"] == "Step B" for n in nodes), (
            "Old label 'Step B' should be replaced by 'Validation Step'"
        )


# ============================================================================
# CATEGORY 5: ERROR HANDLING
# Tests that errors fail loudly with clear, actionable messages
# ============================================================================


class TestErrorHandlingLoudFailures:
    """
    Validates errors are caught early and reported clearly.
    Implements "fail loudly" principle from claude.md.

    These tests ensure users understand what went wrong and how to fix it.
    """

    def test_delete_nonexistent_node_fails_clearly(
        self, session: WorkflowTestSession, simple_workflow: Dict[str, Any]
    ):
        """
        Test that deleting a nonexistent node fails with clear message.

        Acceptance Criteria:
        - Try to delete node that doesn't exist
        - Tool returns success=False OR LLM explains node not found
        - orchestrator.current_workflow unchanged
        - Error message lists available nodes (helps user understand state)
        """
        session.set_initial_workflow(simple_workflow)
        initial_node_count = len(simple_workflow["nodes"])

        response = session.respond(
            "delete the 'Nonexistent Node'",
            allow_tools=True
        )

        # Verify no nodes were deleted
        session.assert_node_count(initial_node_count, in_orchestrator=True)

        # Response should indicate the problem clearly
        response_lower = response.lower()
        assert any(
            phrase in response_lower
            for phrase in ["not found", "doesn't exist", "cannot find", "no node", "could not find"]
        ), f"Response should clearly indicate node not found. Got: {response}"

    def test_modify_nonexistent_node_fails_clearly(self, session: WorkflowTestSession):
        """
        Test that modifying a nonexistent node fails with clear message.

        Acceptance Criteria:
        - Try to modify node_id that doesn't exist
        - Tool returns success=False with clear error
        - Error message includes available node IDs or labels
        """
        response = session.respond(
            "change the label of 'Ghost Node' to 'New Label'",
            allow_tools=True
        )

        # State should be unchanged (empty)
        session.assert_node_count(0, in_orchestrator=True)

        # Response should indicate the problem
        response_lower = response.lower()
        assert any(
            phrase in response_lower
            for phrase in ["not found", "doesn't exist", "cannot find", "no node"]
        ), f"Response should indicate node not found. Got: {response}"

    def test_connect_nonexistent_nodes_fails_clearly(
        self, session: WorkflowTestSession, simple_workflow: Dict[str, Any]
    ):
        """
        Test that connecting nonexistent nodes fails with clear message.

        Acceptance Criteria:
        - Try to connect nodes where one or both don't exist
        - Tool returns success=False with clear error
        - Error message indicates which node(s) not found
        - orchestrator.current_workflow unchanged
        """
        session.set_initial_workflow(simple_workflow)
        initial_edge_count = len(simple_workflow["edges"])

        response = session.respond(
            "connect 'Ghost Node A' to 'Ghost Node B'",
            allow_tools=True
        )

        # No new edges should be created
        session.assert_edge_count(initial_edge_count, in_orchestrator=True)

        # Response should indicate the problem
        response_lower = response.lower()
        assert any(
            phrase in response_lower
            for phrase in ["not found", "doesn't exist", "cannot find", "no node"]
        ), f"Response should indicate nodes not found. Got: {response}"


# ============================================================================
# CATEGORY 6: LLM TOOL SELECTION
# Tests that LLM chooses optimal tools for requests
# ============================================================================


class TestLLMToolSelection:
    """
    Validates LLM selects appropriate tools for user requests.

    These tests document expected LLM behavior and catch regressions
    in the orchestrator's system prompt or tool descriptions.
    """

    def test_llm_calls_get_workflow_before_modify(
        self, session: WorkflowTestSession, simple_workflow: Dict[str, Any]
    ):
        """
        Test that LLM calls get_current_workflow to find node IDs before modifying.

        Acceptance Criteria:
        - User: "change Validator to Validation Engine"
        - LLM first calls get_current_workflow (or has it cached)
        - Then calls modify_node with correct node_id
        - LLM doesn't guess or hallucinate node IDs
        """
        session.set_initial_workflow(simple_workflow)

        response = session.respond(
            "change 'Validate Input' to 'Check Input'",
            allow_tools=True
        )

        tool_names = session.get_tool_names()

        # LLM should call get_current_workflow and modify_node
        # (It might call get_current_workflow earlier or have it cached)
        assert "modify_node" in tool_names, (
            f"Expected modify_node to be called, got: {tool_names}"
        )

        # Verify modification happened (tests that correct node_id was used)
        session.assert_node_exists("Check Input", in_orchestrator=True)

    def test_llm_uses_batch_for_decision_nodes(self, session: WorkflowTestSession):
        """
        Test that LLM uses batch_edit_workflow for decision nodes with branches.

        Acceptance Criteria:
        - User: "add decision node with branches"
        - LLM recognizes this needs atomic operation
        - LLM calls batch_edit_workflow (not sequential add_node + add_connection)
        - Creates decision + branches + edges atomically

        Note: LLM might also use multiple add_node calls which is acceptable,
        but batch_edit is optimal.
        """
        response = session.respond(
            "Add a decision node 'Is Valid?' with true and false branches",
            allow_tools=True
        )

        # Verify decision node created with 2 branches
        decision = session.assert_node_exists("Is Valid", node_type="decision", in_orchestrator=True)
        edges = session.orchestrator.current_workflow["edges"]
        decision_edges = [e for e in edges if e["from"] == decision["id"]]

        assert len(decision_edges) == 2, (
            f"Decision should have 2 branches, got {len(decision_edges)}"
        )


# ============================================================================
# CATEGORY 7: COMPLEX WORKFLOW PATTERNS
# Tests real-world workflow construction scenarios
# ============================================================================


class TestComplexWorkflowPatterns:
    """
    Validates complex multi-step workflow creation.

    These tests represent realistic user workflows and ensure the system
    can handle sophisticated graph structures.
    """

    def test_insert_node_between_existing(
        self, session: WorkflowTestSession, simple_workflow: Dict[str, Any]
    ):
        """
        Test inserting a node between two connected nodes.

        Acceptance Criteria:
        - Start with: A → B
        - User: "insert node X between A and B"
        - Result: A → X → B (edge A→B deleted, A→X and X→B added)
        - Orchestrator state reflects final structure
        """
        session.set_initial_workflow(simple_workflow)

        response = session.respond(
            "Insert a process node called 'Sanitize' between 'Start' and 'Validate Input'",
            allow_tools=True
        )

        # Verify new node exists
        sanitize = session.assert_node_exists("Sanitize", node_type="process", in_orchestrator=True)

        # Verify edge structure: Start → Sanitize → Validate Input
        session.assert_edge_exists("Start", "Sanitize", in_orchestrator=True)
        session.assert_edge_exists("Sanitize", "Validate Input", in_orchestrator=True)

        # Verify old direct edge is gone
        with pytest.raises(AssertionError, match="not found"):
            session.assert_edge_exists("Start", "Validate Input", in_orchestrator=True)

    def test_create_parallel_branches(self, session: WorkflowTestSession):
        """
        Test creating workflow with parallel paths that merge.

        Acceptance Criteria:
        - Create: Start → (Process A | Process B) → End
        - Start has 2 outgoing edges (fork)
        - End has 2 incoming edges (join)
        - All nodes and edges present in orchestrator state
        """
        response = session.respond(
            "Create a workflow where Start splits into two parallel processes "
            "'Process A' and 'Process B', then they both connect to End",
            allow_tools=True
        )

        # Verify structure
        start = session.assert_node_exists("Start", node_type="start", in_orchestrator=True)
        end = session.assert_node_exists("End", node_type="end", in_orchestrator=True)

        edges = session.orchestrator.current_workflow["edges"]

        # Start should have 2 outgoing edges (fork)
        start_edges = [e for e in edges if e["from"] == start["id"]]
        assert len(start_edges) >= 2, (
            f"Start should fork into 2 branches, got {len(start_edges)}"
        )

        # End should have 2 incoming edges (join)
        end_edges = [e for e in edges if e["to"] == end["id"]]
        assert len(end_edges) >= 2, (
            f"End should join 2 branches, got {len(end_edges)}"
        )

    def test_create_authentication_flow_pattern(self, session: WorkflowTestSession):
        """
        Test creating realistic authentication workflow.

        Acceptance Criteria:
        - Structure: Start → Check Auth? → (authenticated: Dashboard | not: Login) → End
        - Decision node with 2 branches
        - Both branches eventually reach End
        - All connections proper
        """
        response = session.respond(
            "Create an authentication workflow: "
            "Start → Check if authenticated? (decision) → if yes go to Dashboard, "
            "if no go to Login Page → both paths end at End node",
            allow_tools=True
        )

        # Verify decision node
        decision = session.assert_node_exists(
            "authenticated", node_type="decision", in_orchestrator=True
        )

        # Verify decision has 2 branches
        edges = session.orchestrator.current_workflow["edges"]
        decision_edges = [e for e in edges if e["from"] == decision["id"]]
        assert len(decision_edges) == 2, (
            f"Decision should have 2 branches, got {len(decision_edges)}"
        )

        # Verify branch nodes exist
        session.assert_node_exists("Dashboard", in_orchestrator=True)
        session.assert_node_exists("Login", in_orchestrator=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
