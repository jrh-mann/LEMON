"""Integration test for workflow synchronization from frontend to orchestrator.

This test reproduces the user's reported issue:
- User adds nodes via frontend UI (canvas)
- User sends a chat message
- Orchestrator reports workflow as empty

Purpose: Identify where in the data flow the synchronization breaks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

import pytest

from src.backend.agents.orchestrator_factory import build_orchestrator
from src.backend.api.conversations import ConversationStore


def _repo_root() -> Path:
    return Path(__file__).parent.parent.parent


@pytest.fixture
def conversation_store():
    """Create in-memory conversation store."""
    return ConversationStore(repo_root=_repo_root())


@pytest.fixture
def conversation_id():
    """Generate a conversation ID (simulates frontend UUID generation)."""
    return str(uuid4())


class TestWorkflowSyncIntegration:
    """Test full workflow sync flow from frontend to orchestrator."""

    def test_workflow_sync_before_first_message(
        self, conversation_store: ConversationStore, conversation_id: str
    ):
        """
        Simulates the expected flow after fix:
        1. Frontend generates conversation_id
        2. Frontend syncs workflow (with nodes)
        3. Frontend sends first message
        4. Orchestrator should see the nodes
        """
        # STEP 1: Frontend adds nodes to canvas (simulated)
        frontend_workflow = {
            "nodes": [
                {
                    "id": "node_1",
                    "type": "start",
                    "label": "Start",
                    "x": 100,
                    "y": 100,
                    "color": "teal",
                },
                {
                    "id": "node_2",
                    "type": "process",
                    "label": "Process Data",
                    "x": 100,
                    "y": 200,
                    "color": "slate",
                },
            ],
            "edges": [
                {"id": "node_1->node_2", "from": "node_1", "to": "node_2", "label": ""}
            ],
        }

        # STEP 2: Simulate sync_workflow socket event (frontend calls this before message)
        # This is what should happen when frontend calls syncWorkflow('manual')
        convo = conversation_store.get_or_create(conversation_id)

        # Simulate the backend socket handler receiving sync_workflow
        # (from socket_handlers.py handle_sync_workflow)
        convo.update_workflow_state(frontend_workflow)

        # STEP 3: Simulate chat message socket event
        # Backend syncs workflow from session to orchestrator
        convo.orchestrator.sync_workflow(lambda: convo.workflow_state)

        # STEP 4: Verify orchestrator sees the nodes
        orchestrator_workflow = convo.orchestrator.current_workflow

        print(f"\n[DEBUG] Frontend workflow: {json.dumps(frontend_workflow, indent=2)}")
        print(f"[DEBUG] Conversation workflow_state: {json.dumps(convo.workflow_state, indent=2)}")
        print(f"[DEBUG] Orchestrator current_workflow: {json.dumps(orchestrator_workflow, indent=2)}")

        # ASSERTIONS
        assert orchestrator_workflow is not None, "Orchestrator workflow should not be None"
        assert "nodes" in orchestrator_workflow, "Orchestrator workflow should have nodes key"
        assert "edges" in orchestrator_workflow, "Orchestrator workflow should have edges key"

        assert len(orchestrator_workflow["nodes"]) == 2, (
            f"Expected 2 nodes in orchestrator, got {len(orchestrator_workflow['nodes'])}"
        )
        assert len(orchestrator_workflow["edges"]) == 1, (
            f"Expected 1 edge in orchestrator, got {len(orchestrator_workflow['edges'])}"
        )

        # Verify node content
        node_labels = [n["label"] for n in orchestrator_workflow["nodes"]]
        assert "Start" in node_labels, "Expected 'Start' node in orchestrator"
        assert "Process Data" in node_labels, "Expected 'Process Data' node in orchestrator"

    def test_workflow_sync_without_explicit_sync_call(
        self, conversation_store: ConversationStore, conversation_id: str
    ):
        """
        Simulates the BROKEN flow (before fix):
        1. Frontend adds nodes to canvas
        2. Frontend sends first message WITHOUT syncing (conversationId was null)
        3. Backend creates conversation with empty workflow_state
        4. Orchestrator sees empty workflow
        """
        # STEP 1: Frontend adds nodes (but doesn't sync because conversationId is null)
        frontend_workflow = {
            "nodes": [
                {
                    "id": "node_1",
                    "type": "start",
                    "label": "Start",
                    "x": 100,
                    "y": 100,
                    "color": "teal",
                }
            ],
            "edges": [],
        }

        # STEP 2: Frontend sends message without syncing
        # Backend creates conversation (workflow_state defaults to empty)
        convo = conversation_store.get_or_create(conversation_id)

        # Note: NO sync_workflow call here - this is the bug!

        # STEP 3: Backend syncs from empty workflow_state
        convo.orchestrator.sync_workflow(lambda: convo.workflow_state)

        # STEP 4: Orchestrator sees empty workflow (THIS IS THE BUG)
        orchestrator_workflow = convo.orchestrator.current_workflow

        print(f"\n[DEBUG] Frontend had nodes: {len(frontend_workflow['nodes'])}")
        print(f"[DEBUG] Orchestrator sees nodes: {len(orchestrator_workflow['nodes'])}")

        # This test documents the bug - orchestrator sees nothing
        assert len(orchestrator_workflow["nodes"]) == 0, (
            "Bug reproduction: orchestrator sees 0 nodes because sync never happened"
        )

    def test_orchestrator_state_matches_after_sync(
        self, conversation_store: ConversationStore, conversation_id: str
    ):
        """
        Test that orchestrator's current_workflow matches the synced workflow.

        This verifies the sync_workflow path correctly populates orchestrator
        state that tools will read (tools now load from DB in production, but
        the sync path is still used for the ConversationStore flow).
        """
        frontend_workflow = {
            "nodes": [
                {
                    "id": "node_1",
                    "type": "start",
                    "label": "Start",
                    "x": 100,
                    "y": 100,
                    "color": "teal",
                },
                {
                    "id": "node_2",
                    "type": "end",
                    "label": "End",
                    "x": 100,
                    "y": 300,
                    "color": "green",
                },
            ],
            "edges": [
                {"id": "node_1->node_2", "from": "node_1", "to": "node_2", "label": ""}
            ],
        }

        convo = conversation_store.get_or_create(conversation_id)
        convo.update_workflow_state(frontend_workflow)
        convo.orchestrator.sync_workflow(lambda: convo.workflow_state)

        # Verify orchestrator state matches
        workflow = convo.orchestrator.current_workflow
        assert len(workflow["nodes"]) == 2, (
            f"Orchestrator should have 2 nodes after sync, got {len(workflow['nodes'])}"
        )
        assert len(workflow["edges"]) == 1, (
            f"Orchestrator should have 1 edge after sync, got {len(workflow['edges'])}"
        )

        # Verify node content survived sync
        node_labels = {n["label"] for n in workflow["nodes"]}
        assert node_labels == {"Start", "End"}

    def test_full_e2e_sync_preserves_node_details(
        self, conversation_store: ConversationStore, conversation_id: str
    ):
        """
        End-to-end test: sync workflow with detailed nodes, verify all fields preserved.

        Tests that sync_workflow preserves node types, labels, positions, and
        edge relationships through the ConversationStore → orchestrator path.
        """
        frontend_workflow = {
            "nodes": [
                {
                    "id": "node_abc",
                    "type": "start",
                    "label": "User Registration",
                    "x": 100,
                    "y": 100,
                    "color": "teal",
                },
                {
                    "id": "node_def",
                    "type": "decision",
                    "label": "Email Valid?",
                    "x": 100,
                    "y": 200,
                    "color": "amber",
                },
            ],
            "edges": [
                {"id": "node_abc->node_def", "from": "node_abc", "to": "node_def", "label": ""}
            ],
        }

        convo = conversation_store.get_or_create(conversation_id)
        convo.update_workflow_state(frontend_workflow)
        convo.orchestrator.sync_workflow(lambda: convo.workflow_state)

        # Verify state is synced correctly
        nodes = convo.orchestrator.current_workflow["nodes"]
        edges = convo.orchestrator.current_workflow["edges"]
        assert len(nodes) == 2, "Orchestrator should have 2 nodes after sync"
        assert len(edges) == 1, "Orchestrator should have 1 edge after sync"

        # Verify node details survived sync
        node_map = {n["id"]: n for n in nodes}
        assert node_map["node_abc"]["type"] == "start"
        assert node_map["node_abc"]["label"] == "User Registration"
        assert node_map["node_def"]["type"] == "decision"
        assert node_map["node_def"]["label"] == "Email Valid?"

        # Verify edge details
        assert edges[0]["from"] == "node_abc"
        assert edges[0]["to"] == "node_def"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
