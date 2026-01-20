"""Test workflow manipulation tools and orchestrator integration.

Tests that the model can successfully:
1. Read current workflow
2. Add new nodes with correct positioning
3. Add connections between nodes using exact node IDs
4. Handle complex multi-step workflows
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

import pytest

from ..agents.orchestrator_factory import build_orchestrator
from ..api.conversations import ConversationStore


def _repo_root() -> Path:
    return Path(__file__).parent.parent.parent.parent


@pytest.fixture
def conversation_store():
    """Create in-memory conversation store."""
    return ConversationStore(repo_root=_repo_root())


@pytest.fixture
def conversation_id():
    """Generate a conversation ID."""
    return str(uuid4())


class TestWorkflowManipulation:
    """Test workflow manipulation tools work correctly."""

    def test_add_node_tool_direct(self, conversation_store, conversation_id):
        """Test adding a node directly via tool."""
        from ..tools.workflow_edit import AddNodeTool

        tool = AddNodeTool()

        # Start with empty workflow
        session_state = {"current_workflow": {"nodes": [], "edges": []}}

        # Add a decision node
        result = tool.execute(
            {"type": "decision", "label": "Patient over 60?", "x": 100, "y": 100},
            session_state=session_state
        )

        print(f"\n[DEBUG] Add node result: {json.dumps(result, indent=2)}")

        assert result["success"] is True, f"Tool failed: {result.get('error')}"
        assert result["action"] == "add_node"
        assert "node" in result
        assert result["node"]["type"] == "decision"
        assert result["node"]["label"] == "Patient over 60?"
        assert "id" in result["node"]

    def test_add_connection_tool_direct(self, conversation_store, conversation_id):
        """Test adding a connection directly via tool."""
        from ..tools.workflow_edit import AddConnectionTool

        tool = AddConnectionTool()

        # Start with workflow containing 2 nodes
        session_state = {
            "current_workflow": {
                "nodes": [
                    {"id": "node_1", "type": "start", "label": "Start", "x": 0, "y": 0, "color": "teal"},
                    {"id": "node_2", "type": "end", "label": "End", "x": 0, "y": 100, "color": "green"},
                ],
                "edges": []
            }
        }

        # Connect them
        result = tool.execute(
            {"from_node_id": "node_1", "to_node_id": "node_2", "label": ""},
            session_state=session_state
        )

        print(f"\n[DEBUG] Add connection result: {json.dumps(result, indent=2)}")

        assert result["success"] is True, f"Tool failed: {result.get('error')}"
        assert result["action"] == "add_connection"
        assert "edge" in result
        assert result["edge"]["from"] == "node_1"
        assert result["edge"]["to"] == "node_2"

    def test_orchestrator_has_workflow_tools(self, conversation_store, conversation_id):
        """Test that orchestrator has access to workflow manipulation tools."""
        convo = conversation_store.get_or_create(conversation_id)

        # Check which tools are available (tools is a ToolRegistry, not a list)
        tool_names = list(convo.orchestrator.tools._tools.keys())

        print(f"\n[DEBUG] Available tools: {tool_names}")

        required_tools = [
            "get_current_workflow",
            "add_node",
            "modify_node",
            "delete_node",
            "add_connection",
            "delete_connection",
        ]

        for tool in required_tools:
            assert tool in tool_names, f"Missing required tool: {tool}"

    def test_add_node_updates_orchestrator_state(self, conversation_store, conversation_id):
        """Test that adding a node via tool updates orchestrator's current_workflow."""
        from ..tools.workflow_edit import AddNodeTool

        convo = conversation_store.get_or_create(conversation_id)

        # Start with empty workflow
        convo.orchestrator.current_workflow = {"nodes": [], "edges": []}

        # Add a node using the tool
        tool = AddNodeTool()
        result = tool.execute(
            {"type": "process", "label": "Process Data", "x": 50, "y": 50},
            session_state={"current_workflow": convo.orchestrator.current_workflow}
        )

        assert result["success"] is True

        # Manually update orchestrator state (this is what respond() does)
        new_node = result["node"]
        convo.orchestrator.current_workflow["nodes"].append(new_node)

        # Verify orchestrator now sees the node
        assert len(convo.orchestrator.current_workflow["nodes"]) == 1
        assert convo.orchestrator.current_workflow["nodes"][0]["label"] == "Process Data"

    def test_get_current_workflow_returns_nodes(self, conversation_store, conversation_id):
        """Test that get_current_workflow tool returns nodes."""
        from ..tools.workflow_edit import GetCurrentWorkflowTool

        convo = conversation_store.get_or_create(conversation_id)

        # Set up workflow with nodes
        convo.orchestrator.current_workflow = {
            "nodes": [
                {"id": "node_abc", "type": "start", "label": "Input", "x": 0, "y": 0, "color": "teal"},
                {"id": "node_def", "type": "decision", "label": "Check condition", "x": 0, "y": 100, "color": "amber"},
            ],
            "edges": [
                {"id": "node_abc->node_def", "from": "node_abc", "to": "node_def", "label": ""}
            ]
        }

        # Get workflow using tool
        tool = GetCurrentWorkflowTool()
        result = tool.execute(
            {},
            session_state={"current_workflow": convo.orchestrator.current_workflow}
        )

        print(f"\n[DEBUG] Get workflow result: {json.dumps(result, indent=2)}")

        assert result["success"] is True
        assert len(result["workflow"]["nodes"]) == 2
        assert len(result["workflow"]["edges"]) == 1
        assert result["node_count"] == 2
        assert result["edge_count"] == 1

    def test_complex_workflow_scenario(self, conversation_store, conversation_id):
        """Test building a complex workflow step by step (simulating orchestrator flow)."""
        from ..tools.workflow_edit import AddNodeTool, AddConnectionTool, GetCurrentWorkflowTool

        convo = conversation_store.get_or_create(conversation_id)
        convo.orchestrator.current_workflow = {"nodes": [], "edges": []}

        # Helper to get current state for tools
        def get_session_state():
            return {"current_workflow": convo.orchestrator.current_workflow}

        # Step 1: Add start node
        add_tool = AddNodeTool()
        result1 = add_tool.execute(
            {"type": "start", "label": "Input", "x": 100, "y": 50},
            session_state=get_session_state()
        )
        assert result1["success"], f"Failed to add start node: {result1.get('error')}"
        start_node_id = result1["node"]["id"]
        convo.orchestrator.current_workflow["nodes"].append(result1["node"])

        # Step 2: Add decision node
        result2 = add_tool.execute(
            {"type": "decision", "label": "Patient over 60?", "x": 100, "y": 150},
            session_state=get_session_state()
        )
        assert result2["success"], f"Failed to add decision node: {result2.get('error')}"
        decision_node_id = result2["node"]["id"]
        convo.orchestrator.current_workflow["nodes"].append(result2["node"])

        # Step 3: Add end node (true branch)
        result3 = add_tool.execute(
            {"type": "end", "label": "Old", "x": 50, "y": 250},
            session_state=get_session_state()
        )
        assert result3["success"], f"Failed to add end node (old): {result3.get('error')}"
        old_node_id = result3["node"]["id"]
        convo.orchestrator.current_workflow["nodes"].append(result3["node"])

        # Step 4: Add end node (false branch)
        result4 = add_tool.execute(
            {"type": "end", "label": "Young", "x": 150, "y": 250},
            session_state=get_session_state()
        )
        assert result4["success"], f"Failed to add end node (young): {result4.get('error')}"
        young_node_id = result4["node"]["id"]
        convo.orchestrator.current_workflow["nodes"].append(result4["node"])

        # Step 5: Connect start to decision
        conn_tool = AddConnectionTool()
        result5 = conn_tool.execute(
            {"from_node_id": start_node_id, "to_node_id": decision_node_id, "label": ""},
            session_state=get_session_state()
        )
        assert result5["success"], f"Failed to connect start->decision: {result5.get('error')}"
        convo.orchestrator.current_workflow["edges"].append(result5["edge"])

        # Step 6: Connect decision to "old" (true branch)
        result6 = conn_tool.execute(
            {"from_node_id": decision_node_id, "to_node_id": old_node_id, "label": "true"},
            session_state=get_session_state()
        )
        assert result6["success"], f"Failed to connect decision->old: {result6.get('error')}"
        convo.orchestrator.current_workflow["edges"].append(result6["edge"])

        # Step 7: Connect decision to "young" (false branch)
        result7 = conn_tool.execute(
            {"from_node_id": decision_node_id, "to_node_id": young_node_id, "label": "false"},
            session_state=get_session_state()
        )
        assert result7["success"], f"Failed to connect decision->young: {result7.get('error')}"
        convo.orchestrator.current_workflow["edges"].append(result7["edge"])

        # Verify final state
        get_tool = GetCurrentWorkflowTool()
        final_result = get_tool.execute({}, session_state=get_session_state())

        print(f"\n[DEBUG] Final workflow: {json.dumps(final_result, indent=2)}")

        assert final_result["node_count"] == 4, f"Expected 4 nodes, got {final_result['node_count']}"
        assert final_result["edge_count"] == 3, f"Expected 3 edges, got {final_result['edge_count']}"

        # Verify node labels
        node_labels = [n["label"] for n in final_result["workflow"]["nodes"]]
        assert "Input" in node_labels
        assert "Patient over 60?" in node_labels
        assert "Old" in node_labels
        assert "Young" in node_labels

        # Verify edge labels
        edge_labels = [e["label"] for e in final_result["workflow"]["edges"]]
        assert "true" in edge_labels
        assert "false" in edge_labels

        print("\n[DEBUG] ✓ Complex workflow scenario passed - all nodes and connections created successfully")

    def test_batch_edit_creates_decision_with_branches(self, conversation_store, conversation_id):
        """Test that batch_edit_workflow can create decision node + branches atomically."""
        from ..tools.workflow_edit import BatchEditWorkflowTool

        convo = conversation_store.get_or_create(conversation_id)
        convo.orchestrator.current_workflow = {"nodes": [], "edges": []}

        tool = BatchEditWorkflowTool()

        # Create decision node with both branches in a single batch operation
        result = tool.execute(
            {
                "operations": [
                    {"op": "add_node", "type": "decision", "label": "Age over 18?", "id": "temp_decision", "x": 100, "y": 100},
                    {"op": "add_node", "type": "end", "label": "Adult", "id": "temp_adult", "x": 50, "y": 200},
                    {"op": "add_node", "type": "end", "label": "Minor", "id": "temp_minor", "x": 150, "y": 200},
                    {"op": "add_connection", "from": "temp_decision", "to": "temp_adult", "label": "true"},
                    {"op": "add_connection", "from": "temp_decision", "to": "temp_minor", "label": "false"},
                ]
            },
            session_state={"current_workflow": convo.orchestrator.current_workflow}
        )

        print(f"\n[DEBUG] Batch edit result: {json.dumps(result, indent=2)}")

        assert result["success"] is True, f"Batch operation failed: {result.get('error')}"
        assert result["action"] == "batch_edit"
        assert result["operation_count"] == 5

        # Verify workflow has all nodes and connections
        workflow = result["workflow"]
        assert len(workflow["nodes"]) == 3, f"Expected 3 nodes, got {len(workflow['nodes'])}"
        assert len(workflow["edges"]) == 2, f"Expected 2 edges, got {len(workflow['edges'])}"

        # Verify node types
        node_types = [n["type"] for n in workflow["nodes"]]
        assert node_types.count("decision") == 1
        assert node_types.count("end") == 2

        # Verify edge labels
        edge_labels = [e["label"] for e in workflow["edges"]]
        assert "true" in edge_labels
        assert "false" in edge_labels

        print("\n[DEBUG] ✓ Batch edit successfully created decision node with both branches")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
