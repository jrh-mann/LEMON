"""Integration tests for force delete workflow input feature.

Tests the full flow through the orchestrator to ensure nodes are properly updated
when removing workflow inputs with force=true.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from ..agents.orchestrator_factory import build_orchestrator


# Disable MCP for these tests to ensure direct tool execution
@pytest.fixture(autouse=True)
def disable_mcp(monkeypatch):
    """Disable MCP mode for all tests in this module."""
    monkeypatch.setenv("LEMON_USE_MCP", "false")


@pytest.fixture
def repo_root():
    """Get repository root."""
    return Path(__file__).parent.parent.parent.parent


@pytest.fixture
def orchestrator(repo_root):
    """Create an orchestrator instance."""
    orch = build_orchestrator(repo_root=repo_root)
    # Explicitly initialize state (similar to working tests)
    orch.workflow_analysis = {"inputs": [], "outputs": [], "tree": {}, "doubts": []}
    orch.current_workflow = {"nodes": [], "edges": []}
    return orch


class TestForceDeleteIntegration:
    """Integration tests for force delete feature through orchestrator."""

    def test_force_delete_fails_without_force_flag(self, orchestrator):
        """Test that deletion fails by default when nodes reference the input."""
        logging.basicConfig(level=logging.DEBUG)

        # Step 1: Add a workflow input
        result1 = orchestrator.run_tool(
            "add_workflow_input",
            {"name": "Patient Age", "type": "number", "description": "Patient's age in years"}
        )

        print(f"\n[TEST] Add input result: {json.dumps(result1.data, indent=2)}")
        assert result1.success
        assert len(orchestrator.workflow["inputs"]) == 1

        # Step 2: Add a node that references the input
        result2 = orchestrator.run_tool(
            "add_node",
            {
                "type": "decision",
                "label": "Age > 60?",
                "input_ref": "Patient Age",
                "x": 100,
                "y": 100
            }
        )

        print(f"\n[TEST] Add node result: {json.dumps(result2.data, indent=2)}")
        assert result2.success
        assert len(orchestrator.workflow["nodes"]) == 1
        assert orchestrator.workflow["nodes"][0]["input_ref"] == "Patient Age"

        # Step 3: Try to delete input WITHOUT force (should fail)
        result3 = orchestrator.run_tool(
            "remove_workflow_input",
            {"name": "Patient Age"}
        )

        print(f"\n[TEST] Remove input (no force) result: {json.dumps(result3.data, indent=2)}")

        # Should fail
        assert not result3.success
        assert "Cannot remove input 'Patient Age'" in result3.error
        assert "referenced by 1 node(s)" in result3.error
        assert "force=true" in result3.error

        # Input should still exist
        assert len(orchestrator.workflow["inputs"]) == 1

        # Node should still have input_ref
        assert len(orchestrator.workflow["nodes"]) == 1
        assert orchestrator.workflow["nodes"][0]["input_ref"] == "Patient Age"

    def test_force_delete_cascades_successfully(self, orchestrator):
        """Test that force=true removes input and clears input_ref from nodes."""
        logging.basicConfig(level=logging.DEBUG)

        # Step 1: Add a workflow input
        result1 = orchestrator.run_tool(
            "add_workflow_input",
            {"name": "Blood Pressure", "type": "number"}
        )

        print(f"\n[TEST] Add input result: {json.dumps(result1.data, indent=2)}")
        assert result1.success

        # Step 2: Add TWO nodes that reference the input
        result2 = orchestrator.run_tool(
            "add_node",
            {
                "type": "decision",
                "label": "BP > 140?",
                "input_ref": "Blood Pressure",
                "x": 100,
                "y": 100
            }
        )
        print(f"\n[TEST] Add node 1 result: {json.dumps(result2.data, indent=2)}")
        assert result2.success

        result3 = orchestrator.run_tool(
            "add_node",
            {
                "type": "decision",
                "label": "BP < 90?",
                "input_ref": "Blood Pressure",
                "x": 100,
                "y": 200
            }
        )
        print(f"\n[TEST] Add node 2 result: {json.dumps(result3.data, indent=2)}")
        assert result3.success

        # Verify both nodes have input_ref
        assert len(orchestrator.workflow["nodes"]) == 2
        assert orchestrator.workflow["nodes"][0]["input_ref"] == "Blood Pressure"
        assert orchestrator.workflow["nodes"][1]["input_ref"] == "Blood Pressure"

        print(f"\n[TEST] Workflow before force delete:")
        print(f"  Inputs: {len(orchestrator.workflow['inputs'])}")
        print(f"  Nodes: {len(orchestrator.workflow['nodes'])}")
        for i, node in enumerate(orchestrator.workflow['nodes']):
            print(f"    Node {i}: id={node['id']}, label={node['label']}, input_ref={node.get('input_ref', 'None')}")

        # Step 3: Force delete the input
        result4 = orchestrator.run_tool(
            "remove_workflow_input",
            {"name": "Blood Pressure", "force": True}
        )

        print(f"\n[TEST] Force delete result: {json.dumps(result4.data, indent=2)}")

        # Should succeed
        assert result4.success
        assert "Removed input 'Blood Pressure'" in result4.message
        assert "cleared references from 2 node(s)" in result4.message
        assert result4.data.get("affected_nodes") == 2

        # Input should be removed
        assert len(orchestrator.workflow["inputs"]) == 0

        print(f"\n[TEST] Workflow after force delete:")
        print(f"  Inputs: {len(orchestrator.workflow['inputs'])}")
        print(f"  Nodes: {len(orchestrator.workflow['nodes'])}")
        for i, node in enumerate(orchestrator.workflow['nodes']):
            print(f"    Node {i}: id={node['id']}, label={node['label']}, input_ref={node.get('input_ref', 'None')}")

        # CRITICAL: Nodes should NO LONGER have input_ref
        assert len(orchestrator.workflow["nodes"]) == 2
        assert "input_ref" not in orchestrator.workflow["nodes"][0], \
            f"Node 0 still has input_ref: {orchestrator.workflow['nodes'][0].get('input_ref')}"
        assert "input_ref" not in orchestrator.workflow["nodes"][1], \
            f"Node 1 still has input_ref: {orchestrator.workflow['nodes'][1].get('input_ref')}"

    def test_force_delete_with_multiple_nodes_shows_summary(self, orchestrator):
        """Test that force delete with many nodes shows proper summary."""
        logging.basicConfig(level=logging.DEBUG)

        # Add input
        orchestrator.run_tool(
            "add_workflow_input",
            {"name": "Temperature", "type": "number"}
        )

        # Add 5 nodes that reference it
        labels = ["Temp > 38?", "Temp < 36?", "Normal temp?", "High fever?", "Hypothermia?"]
        for i, label in enumerate(labels):
            orchestrator.run_tool(
                "add_node",
                {
                    "type": "decision",
                    "label": label,
                    "input_ref": "Temperature",
                    "x": 100,
                    "y": 100 * i
                }
            )

        # Verify all nodes have input_ref
        assert len(orchestrator.workflow["nodes"]) == 5
        for node in orchestrator.workflow["nodes"]:
            assert node.get("input_ref") == "Temperature"

        # Force delete
        result = orchestrator.run_tool(
            "remove_workflow_input",
            {"name": "Temperature", "force": True}
        )

        print(f"\n[TEST] Force delete result: {json.dumps(result.data, indent=2)}")

        # Should succeed and show summary
        assert result.success
        assert "cleared references from 5 node(s)" in result.message
        assert result.data.get("affected_nodes") == 5

        # All nodes should have input_ref removed
        for i, node in enumerate(orchestrator.workflow["nodes"]):
            assert "input_ref" not in node, \
                f"Node {i} ({node['label']}) still has input_ref: {node.get('input_ref')}"

    def test_force_delete_unused_input_succeeds_immediately(self, orchestrator):
        """Test that deleting an unused input succeeds without force flag."""
        # Add input that's NOT referenced by any nodes
        result1 = orchestrator.run_tool(
            "add_workflow_input",
            {"name": "Unused Input", "type": "string"}
        )
        assert result1.success

        # Delete without force should work (no references)
        result2 = orchestrator.run_tool(
            "remove_workflow_input",
            {"name": "Unused Input"}
        )

        print(f"\n[TEST] Remove unused input result: {json.dumps(result2.data, indent=2)}")

        assert result2.success
        assert "Removed input 'Unused Input'" in result2.message
        assert len(orchestrator.workflow["inputs"]) == 0


if __name__ == "__main__":
    # Allow running tests directly
    pytest.main([__file__, "-xvs"])
