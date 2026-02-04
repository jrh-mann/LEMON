"""Integration tests for force delete workflow variable feature.

Tests the full flow through the orchestrator to ensure nodes are properly updated
when removing workflow variables with force=true. Uses the new condition system
where decision nodes reference variables via condition.input_id.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import uuid4

import pytest

from ..agents.orchestrator_factory import build_orchestrator
from ..storage.workflows import WorkflowStore


def _repo_root() -> Path:
    return Path(__file__).parent.parent.parent.parent


# Disable MCP for these tests to ensure direct tool execution
@pytest.fixture(autouse=True)
def disable_mcp(monkeypatch):
    """Disable MCP mode for all tests in this module."""
    monkeypatch.setenv("LEMON_USE_MCP", "false")


@pytest.fixture
def orchestrator_with_workflow(tmp_path):
    """Create an orchestrator with a proper workflow_store, user_id, and test workflow.
    
    This fixture sets up the orchestrator in the same way the real app does,
    ensuring tools have access to workflow_store and user_id for database operations.
    """
    # Create orchestrator
    orch = build_orchestrator(repo_root=_repo_root())
    
    # Create in-memory workflow store for testing
    db_path = tmp_path / "test_workflows.sqlite"
    workflow_store = WorkflowStore(db_path)
    
    # Set up orchestrator with workflow store and test user
    test_user_id = f"test_user_{uuid4().hex[:8]}"
    orch.workflow_store = workflow_store
    orch.user_id = test_user_id
    
    # Create a test workflow using the create_workflow tool
    result = orch.run_tool("create_workflow", {
        "name": "Test Workflow",
        "description": "Test workflow for force delete tests",
        "output_type": "string"
    })
    
    assert result.success, f"Failed to create test workflow: {result.error}"
    
    # Set current_workflow_id to the newly created workflow
    workflow_id = result.data.get("workflow_id")
    assert workflow_id, "create_workflow did not return workflow_id"
    orch.current_workflow_id = workflow_id
    
    return orch


class TestForceDeleteIntegration:
    """Integration tests for force delete feature through orchestrator."""

    def test_force_delete_fails_without_force_flag(self, orchestrator_with_workflow):
        """Test that deletion fails by default when nodes reference the variable in condition."""
        logging.basicConfig(level=logging.DEBUG)
        orchestrator = orchestrator_with_workflow

        # Step 1: Add a workflow variable
        result1 = orchestrator.run_tool(
            "add_workflow_variable",
            {"name": "Patient Age", "type": "number", "description": "Patient's age in years"}
        )

        print(f"\n[TEST] Add variable result: {json.dumps(result1.data, indent=2)}")
        assert result1.success
        assert len(orchestrator.workflow["inputs"]) == 1
        var_id = result1.data["variable"]["id"]  # e.g., "var_patient_age_int"

        # Step 2: Add a node with condition that references the variable
        result2 = orchestrator.run_tool(
            "add_node",
            {
                "type": "decision",
                "label": "Age > 60?",
                "condition": {
                    "input_id": var_id,
                    "comparator": "gt",
                    "value": 60
                },
                "x": 100,
                "y": 100
            }
        )

        print(f"\n[TEST] Add node result: {json.dumps(result2.data, indent=2)}")
        assert result2.success
        assert len(orchestrator.workflow["nodes"]) == 1
        assert orchestrator.workflow["nodes"][0]["condition"]["input_id"] == var_id

        # Step 3: Try to delete variable WITHOUT force (should fail)
        result3 = orchestrator.run_tool(
            "remove_workflow_variable",
            {"name": "Patient Age"}
        )

        print(f"\n[TEST] Remove variable (no force) result: {json.dumps(result3.data, indent=2)}")

        # Should fail
        assert not result3.success
        assert "Cannot remove variable 'Patient Age'" in result3.error
        assert "referenced by 1 node(s)" in result3.error
        assert "force=true" in result3.error

        # Variable should still exist
        assert len(orchestrator.workflow["inputs"]) == 1

        # Node should still have condition
        assert len(orchestrator.workflow["nodes"]) == 1
        assert orchestrator.workflow["nodes"][0]["condition"]["input_id"] == var_id

    def test_force_delete_cascades_successfully(self, orchestrator_with_workflow):
        """Test that force=true removes variable and clears condition from nodes."""
        logging.basicConfig(level=logging.DEBUG)
        orchestrator = orchestrator_with_workflow

        # Step 1: Add a workflow variable
        result1 = orchestrator.run_tool(
            "add_workflow_variable",
            {"name": "Blood Pressure", "type": "number"}
        )

        print(f"\n[TEST] Add variable result: {json.dumps(result1.data, indent=2)}")
        assert result1.success
        var_id = result1.data["variable"]["id"]

        # Step 2: Add TWO nodes with conditions that reference the variable
        result2 = orchestrator.run_tool(
            "add_node",
            {
                "type": "decision",
                "label": "BP > 140?",
                "condition": {
                    "input_id": var_id,
                    "comparator": "gt",
                    "value": 140
                },
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
                "condition": {
                    "input_id": var_id,
                    "comparator": "lt",
                    "value": 90
                },
                "x": 100,
                "y": 200
            }
        )
        print(f"\n[TEST] Add node 2 result: {json.dumps(result3.data, indent=2)}")
        assert result3.success

        # Verify both nodes have condition
        assert len(orchestrator.workflow["nodes"]) == 2
        assert orchestrator.workflow["nodes"][0]["condition"]["input_id"] == var_id
        assert orchestrator.workflow["nodes"][1]["condition"]["input_id"] == var_id

        print(f"\n[TEST] Workflow before force delete:")
        print(f"  Variables: {len(orchestrator.workflow['inputs'])}")
        print(f"  Nodes: {len(orchestrator.workflow['nodes'])}")
        for i, node in enumerate(orchestrator.workflow['nodes']):
            print(f"    Node {i}: id={node['id']}, label={node['label']}, condition={node.get('condition')}")

        # Step 3: Force delete the variable
        result4 = orchestrator.run_tool(
            "remove_workflow_variable",
            {"name": "Blood Pressure", "force": True}
        )

        print(f"\n[TEST] Force delete result: {json.dumps(result4.data, indent=2)}")

        # Should succeed
        assert result4.success
        assert "Removed variable 'Blood Pressure'" in result4.message
        assert "cleared references from 2 node(s)" in result4.message
        assert result4.data.get("affected_nodes") == 2

        # Variable should be removed
        assert len(orchestrator.workflow["inputs"]) == 0

        print(f"\n[TEST] Workflow after force delete:")
        print(f"  Variables: {len(orchestrator.workflow['inputs'])}")
        print(f"  Nodes: {len(orchestrator.workflow['nodes'])}")
        for i, node in enumerate(orchestrator.workflow['nodes']):
            print(f"    Node {i}: id={node['id']}, label={node['label']}, condition={node.get('condition')}")

        # CRITICAL: Nodes should NO LONGER have condition
        assert len(orchestrator.workflow["nodes"]) == 2
        assert "condition" not in orchestrator.workflow["nodes"][0], \
            f"Node 0 still has condition: {orchestrator.workflow['nodes'][0].get('condition')}"
        assert "condition" not in orchestrator.workflow["nodes"][1], \
            f"Node 1 still has condition: {orchestrator.workflow['nodes'][1].get('condition')}"

    def test_force_delete_with_multiple_nodes_shows_summary(self, orchestrator_with_workflow):
        """Test that force delete with many nodes shows proper summary."""
        logging.basicConfig(level=logging.DEBUG)
        orchestrator = orchestrator_with_workflow

        # Add variable
        result = orchestrator.run_tool(
            "add_workflow_variable",
            {"name": "Temperature", "type": "number"}
        )
        var_id = result.data["variable"]["id"]

        # Add 5 nodes with conditions that reference it
        labels = ["Temp > 38?", "Temp < 36?", "Normal temp?", "High fever?", "Hypothermia?"]
        comparators = ["gt", "lt", "gte", "gt", "lt"]
        values = [38, 36, 36, 40, 35]

        for i, (label, comp, val) in enumerate(zip(labels, comparators, values)):
            orchestrator.run_tool(
                "add_node",
                {
                    "type": "decision",
                    "label": label,
                    "condition": {
                        "input_id": var_id,
                        "comparator": comp,
                        "value": val
                    },
                    "x": 100,
                    "y": 100 * i
                }
            )

        # Verify all nodes have condition
        assert len(orchestrator.workflow["nodes"]) == 5
        for node in orchestrator.workflow["nodes"]:
            assert node.get("condition") is not None
            assert node["condition"]["input_id"] == var_id

        # Force delete
        result = orchestrator.run_tool(
            "remove_workflow_variable",
            {"name": "Temperature", "force": True}
        )

        print(f"\n[TEST] Force delete result: {json.dumps(result.data, indent=2)}")

        # Should succeed and show summary
        assert result.success
        assert "cleared references from 5 node(s)" in result.message
        assert result.data.get("affected_nodes") == 5

        # All nodes should have condition removed
        for i, node in enumerate(orchestrator.workflow["nodes"]):
            assert "condition" not in node, \
                f"Node {i} ({node['label']}) still has condition: {node.get('condition')}"

    def test_force_delete_unused_variable_succeeds_immediately(self, orchestrator_with_workflow):
        """Test that deleting an unused variable succeeds without force flag."""
        orchestrator = orchestrator_with_workflow
        # Add variable that's NOT referenced by any nodes
        result1 = orchestrator.run_tool(
            "add_workflow_variable",
            {"name": "Unused Variable", "type": "string"}
        )
        assert result1.success

        # Delete without force should work (no references)
        result2 = orchestrator.run_tool(
            "remove_workflow_variable",
            {"name": "Unused Variable"}
        )

        print(f"\n[TEST] Remove unused variable result: {json.dumps(result2.data, indent=2)}")

        assert result2.success
        assert "Removed variable 'Unused Variable'" in result2.message
        assert len(orchestrator.workflow["inputs"]) == 0


if __name__ == "__main__":
    # Allow running tests directly
    pytest.main([__file__, "-xvs"])
