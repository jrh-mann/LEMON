"""Test workflow manipulation tools and orchestrator integration.

Tests that tools can successfully:
1. Read current workflow from DB
2. Add new nodes with correct positioning
3. Add connections between nodes using exact node IDs
4. Handle complex multi-step workflows via batch_edit_workflow
5. Orchestrator registry has all required tools

All tests go through orchestrator.run_tool() which builds the proper
session_state with workflow_store, user_id, and current_workflow_id.
"""

from __future__ import annotations

import json

import pytest

from ..api.conversations import ConversationStore


class TestWorkflowManipulation:
    """Test workflow manipulation tools work correctly."""

    def test_add_node_tool_direct(self, orchestrator_with_workflow):
        """Test adding a node via orchestrator.run_tool."""
        orch = orchestrator_with_workflow

        result = orch.run_tool(
            "add_node",
            {"type": "process", "label": "Calculate BMI", "x": 100, "y": 100},
        )

        assert result.success, f"Tool failed: {result.error}"
        assert result.data["action"] == "add_node"
        assert "node" in result.data
        assert result.data["node"]["type"] == "process"
        assert result.data["node"]["label"] == "Calculate BMI"
        assert "id" in result.data["node"]

    def test_add_connection_tool_direct(self, orchestrator_with_workflow):
        """Test adding a connection via orchestrator.run_tool."""
        orch = orchestrator_with_workflow

        # First add two nodes
        r1 = orch.run_tool("add_node", {"type": "start", "label": "Start", "x": 0, "y": 0})
        r2 = orch.run_tool("add_node", {"type": "end", "label": "End", "x": 0, "y": 100})
        assert r1.success and r2.success

        node1_id = r1.data["node"]["id"]
        node2_id = r2.data["node"]["id"]

        # Connect them
        result = orch.run_tool(
            "add_connection",
            {"from_node_id": node1_id, "to_node_id": node2_id, "label": ""},
        )

        assert result.success, f"Tool failed: {result.error}"
        assert result.data["action"] == "add_connection"
        assert "edge" in result.data
        assert result.data["edge"]["from"] == node1_id
        assert result.data["edge"]["to"] == node2_id

    def test_orchestrator_has_workflow_tools(self, orchestrator_with_workflow):
        """Test that orchestrator has access to workflow manipulation tools."""
        orch = orchestrator_with_workflow
        tool_names = list(orch.tools._tools.keys())

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

    def test_add_node_updates_orchestrator_state(self, orchestrator_with_workflow):
        """Test that adding a node via run_tool updates orchestrator's state via DB refresh."""
        orch = orchestrator_with_workflow

        result = orch.run_tool(
            "add_node",
            {"type": "process", "label": "Process Data", "x": 50, "y": 50},
        )
        assert result.success

        # run_tool calls refresh_workflow_from_db — orchestrator should see the node
        assert len(orch.current_workflow["nodes"]) == 1
        assert orch.current_workflow["nodes"][0]["label"] == "Process Data"

    def test_get_current_workflow_returns_nodes(self, orchestrator_with_workflow):
        """Test that get_current_workflow tool returns nodes from DB."""
        orch = orchestrator_with_workflow

        # Add nodes via orchestrator so they're in the DB
        orch.run_tool("add_node", {"type": "start", "label": "Input", "x": 0, "y": 0})
        orch.run_tool("add_node", {"type": "process", "label": "Process Data", "x": 0, "y": 100})

        # Now get the workflow
        result = orch.run_tool("get_current_workflow", {})

        assert result.success
        assert len(result.data["workflow"]["nodes"]) == 2
        assert result.data["node_count"] == 2

    def test_complex_workflow_scenario(self, orchestrator_with_workflow):
        """Test building a complex workflow step by step via orchestrator.run_tool.

        Decision nodes require a condition referencing a variable, so we
        register a variable first.
        """
        orch = orchestrator_with_workflow

        # Register a variable so the decision node can reference it
        var_result = orch.run_tool(
            "add_workflow_variable",
            {"name": "Patient Age", "type": "number"},
        )
        assert var_result.success
        var_id = var_result.data["variable"]["id"]

        # Step 1: Add start node
        r1 = orch.run_tool("add_node", {"type": "start", "label": "Input", "x": 100, "y": 50})
        assert r1.success, f"Failed to add start node: {r1.error}"
        start_id = r1.data["node"]["id"]

        # Step 2: Add decision node (with condition)
        r2 = orch.run_tool("add_node", {
            "type": "decision", "label": "Patient over 60?", "x": 100, "y": 150,
            "condition": {"input_id": var_id, "comparator": "gt", "value": 60},
        })
        assert r2.success, f"Failed to add decision node: {r2.error}"
        decision_id = r2.data["node"]["id"]

        # Step 3: Add end node (true branch)
        r3 = orch.run_tool("add_node", {"type": "end", "label": "Old", "x": 50, "y": 250})
        assert r3.success
        old_id = r3.data["node"]["id"]

        # Step 4: Add end node (false branch)
        r4 = orch.run_tool("add_node", {"type": "end", "label": "Young", "x": 150, "y": 250})
        assert r4.success
        young_id = r4.data["node"]["id"]

        # Step 5-7: Connect nodes
        assert orch.run_tool("add_connection", {"from_node_id": start_id, "to_node_id": decision_id, "label": ""}).success
        assert orch.run_tool("add_connection", {"from_node_id": decision_id, "to_node_id": old_id, "label": "true"}).success
        assert orch.run_tool("add_connection", {"from_node_id": decision_id, "to_node_id": young_id, "label": "false"}).success

        # Verify final state from DB
        final = orch.run_tool("get_current_workflow", {})
        assert final.data["node_count"] == 4, f"Expected 4 nodes, got {final.data['node_count']}"
        assert final.data["edge_count"] == 3, f"Expected 3 edges, got {final.data['edge_count']}"

        node_labels = [n["label"] for n in final.data["workflow"]["nodes"]]
        assert "Input" in node_labels
        assert "Patient over 60?" in node_labels
        assert "Old" in node_labels
        assert "Young" in node_labels

        edge_labels = [e["label"] for e in final.data["workflow"]["edges"]]
        assert "true" in edge_labels
        assert "false" in edge_labels

    def test_batch_edit_creates_decision_with_branches(self, orchestrator_with_workflow):
        """Test that batch_edit_workflow can create decision node + branches atomically.

        Decision nodes require a condition, so we register a variable first.
        """
        orch = orchestrator_with_workflow

        # Register variable for the decision condition
        var_result = orch.run_tool(
            "add_workflow_variable",
            {"name": "Patient Age", "type": "number"},
        )
        assert var_result.success
        var_id = var_result.data["variable"]["id"]

        result = orch.run_tool(
            "batch_edit_workflow",
            {
                "operations": [
                    {
                        "op": "add_node", "type": "decision", "label": "Age over 18?",
                        "id": "temp_decision", "x": 100, "y": 100,
                        "condition": {"input_id": var_id, "comparator": "gt", "value": 18},
                    },
                    {"op": "add_node", "type": "end", "label": "Adult", "id": "temp_adult", "x": 50, "y": 200},
                    {"op": "add_node", "type": "end", "label": "Minor", "id": "temp_minor", "x": 150, "y": 200},
                    {"op": "add_connection", "from": "temp_decision", "to": "temp_adult", "label": "true"},
                    {"op": "add_connection", "from": "temp_decision", "to": "temp_minor", "label": "false"},
                ]
            },
        )

        assert result.success, f"Batch operation failed: {result.error}"
        assert result.data["action"] == "batch_edit"
        assert result.data["operation_count"] == 5

        workflow = result.data["workflow"]
        assert len(workflow["nodes"]) == 3, f"Expected 3 nodes, got {len(workflow['nodes'])}"
        assert len(workflow["edges"]) == 2, f"Expected 2 edges, got {len(workflow['edges'])}"

        node_types = [n["type"] for n in workflow["nodes"]]
        assert node_types.count("decision") == 1
        assert node_types.count("end") == 2

        edge_labels = [e["label"] for e in workflow["edges"]]
        assert "true" in edge_labels
        assert "false" in edge_labels


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
