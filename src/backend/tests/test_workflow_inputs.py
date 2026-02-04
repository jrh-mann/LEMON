"""Test workflow variable management and decision node conditions.

Tests the complete flow:
1. Register variables with add_workflow_variable
2. Create decision nodes that reference variables via condition
3. Validate condition references
4. List and remove variables

All tests use the orchestrator pattern with proper workflow_store and user_id
setup, since tools now require workflow_id for multi-workflow architecture.
"""

from __future__ import annotations

import json
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
        "description": "Test workflow for unit tests",
        "output_type": "string"
    })
    
    assert result.success, f"Failed to create test workflow: {result.error}"
    
    # Set current_workflow_id to the newly created workflow
    workflow_id = result.data.get("workflow_id")
    assert workflow_id, "create_workflow did not return workflow_id"
    orch.current_workflow_id = workflow_id
    
    return orch


class TestWorkflowVariableManagement:
    """Test variable registration and management."""

    def test_add_workflow_variable_basic(self, orchestrator_with_workflow):
        """Test adding a simple workflow variable."""
        orch = orchestrator_with_workflow
        
        result = orch.run_tool("add_workflow_variable", {
            "name": "Patient Age",
            "type": "number",
            "description": "Patient's age in years"
        })

        print(f"\n[DEBUG] Add variable result: {json.dumps(result.data, indent=2)}")

        assert result.success, f"Failed to add variable: {result.error}"
        assert "variable" in result.data
        assert result.data["variable"]["name"] == "Patient Age"
        # Type is converted to internal format: "number" is the canonical type
        assert result.data["variable"]["type"] == "number"
        assert result.data["variable"]["description"] == "Patient's age in years"
        # ID is auto-generated
        assert result.data["variable"]["id"] == "var_patient_age_number"

        # Verify it was added to orchestrator state
        assert len(orch.workflow["inputs"]) == 1
        assert orch.workflow["inputs"][0]["name"] == "Patient Age"

    def test_add_workflow_variable_with_enum(self, orchestrator_with_workflow):
        """Test adding an enum variable."""
        orch = orchestrator_with_workflow
        
        result = orch.run_tool("add_workflow_variable", {
            "name": "Patient Gender",
            "type": "enum",
            "enum_values": ["Male", "Female", "Other"]
        })

        assert result.success
        assert result.data["variable"]["type"] == "enum"
        assert result.data["variable"]["enum_values"] == ["Male", "Female", "Other"]

    def test_add_workflow_variable_with_range(self, orchestrator_with_workflow):
        """Test adding a number variable with range constraints."""
        orch = orchestrator_with_workflow
        
        result = orch.run_tool("add_workflow_variable", {
            "name": "Blood Glucose",
            "type": "number",
            "range_min": 0,
            "range_max": 600
        })

        assert result.success
        assert result.data["variable"]["range"] == {"min": 0, "max": 600}

    def test_add_duplicate_variable_fails(self, orchestrator_with_workflow):
        """Test that adding duplicate variable (case-insensitive) fails."""
        orch = orchestrator_with_workflow
        
        # Add first variable
        result1 = orch.run_tool("add_workflow_variable", {
            "name": "Patient Age", "type": "number"
        })
        assert result1.success

        # Try to add duplicate (exact case)
        result2 = orch.run_tool("add_workflow_variable", {
            "name": "Patient Age", "type": "number"
        })
        assert not result2.success
        assert "already exists" in result2.error.lower()

        # Try to add duplicate (different case)
        result3 = orch.run_tool("add_workflow_variable", {
            "name": "patient age", "type": "number"
        })
        assert not result3.success
        assert "already exists" in result3.error.lower()

    def test_list_workflow_variables(self, orchestrator_with_workflow):
        """Test listing all registered variables."""
        orch = orchestrator_with_workflow
        
        # Add multiple variables
        orch.run_tool("add_workflow_variable", {"name": "Patient Age", "type": "number"})
        orch.run_tool("add_workflow_variable", {"name": "Blood Glucose", "type": "number"})

        # List variables
        result = orch.run_tool("list_workflow_variables", {})

        print(f"\n[DEBUG] List variables result: {json.dumps(result.data, indent=2)}")

        assert result.success
        assert len(result.data["variables"]) == 2
        assert result.data["count"] == 2

        names = [var["name"] for var in result.data["variables"]]
        assert "Patient Age" in names
        assert "Blood Glucose" in names

    def test_remove_workflow_variable(self, orchestrator_with_workflow):
        """Test removing a workflow variable."""
        orch = orchestrator_with_workflow
        
        # Add variable
        orch.run_tool("add_workflow_variable", {"name": "Patient Age", "type": "number"})
        assert len(orch.workflow["inputs"]) == 1

        # Remove variable (case-insensitive)
        result = orch.run_tool("remove_workflow_variable", {"name": "patient age"})

        print(f"\n[DEBUG] Remove variable result: {json.dumps(result.data, indent=2)}")

        assert result.success
        assert len(orch.workflow["inputs"]) == 0

    def test_remove_variable_with_condition_references_fails(self, orchestrator_with_workflow):
        """Test that removing a variable fails if nodes reference it in condition (without force)."""
        orch = orchestrator_with_workflow

        # Add variable
        result1 = orch.run_tool("add_workflow_variable", {"name": "Patient Age", "type": "number"})
        assert result1.success
        var_id = result1.data["variable"]["id"]

        # Add TWO nodes with conditions that reference the variable
        result2 = orch.run_tool("add_node", {
            "type": "decision",
            "label": "Age > 60?",
            "x": 100,
            "y": 100,
            "condition": {"input_id": var_id, "comparator": "gt", "value": 60}
        })
        assert result2.success

        result3 = orch.run_tool("add_node", {
            "type": "decision",
            "label": "Age > 18?",
            "x": 100,
            "y": 200,
            "condition": {"input_id": var_id, "comparator": "gt", "value": 18}
        })
        assert result3.success

        # Try to remove variable WITHOUT force (should fail)
        result = orch.run_tool("remove_workflow_variable", {"name": "Patient Age"})
        
        print(f"\n[DEBUG] Remove without force result: {json.dumps(result.data, indent=2)}")
        
        assert not result.success
        assert "referenced by 2 node(s)" in result.error
        assert "force=true" in result.error

    def test_remove_variable_force_cascades(self, orchestrator_with_workflow):
        """Test that force=true removes variable and clears condition from nodes."""
        orch = orchestrator_with_workflow

        # Add variable
        result1 = orch.run_tool("add_workflow_variable", {"name": "Patient Age", "type": "number"})
        assert result1.success
        var_id = result1.data["variable"]["id"]

        # Add TWO nodes with conditions that reference the variable
        result2 = orch.run_tool("add_node", {
            "type": "decision",
            "label": "Age > 60?",
            "x": 100,
            "y": 100,
            "condition": {"input_id": var_id, "comparator": "gt", "value": 60}
        })
        assert result2.success

        result3 = orch.run_tool("add_node", {
            "type": "decision",
            "label": "Age > 18?",
            "x": 100,
            "y": 200,
            "condition": {"input_id": var_id, "comparator": "gt", "value": 18}
        })
        assert result3.success

        # Remove variable WITH force=true (should cascade)
        result = orch.run_tool("remove_workflow_variable", {"name": "Patient Age", "force": True})

        print(f"\n[DEBUG] Force remove variable result: {json.dumps(result.data, indent=2)}")

        # Should succeed
        assert result.success
        assert "Removed variable 'Patient Age'" in result.data["message"]
        assert "cleared references from 2 node(s)" in result.data["message"]
        assert result.data["affected_nodes"] == 2

        # Variable should be removed
        assert len(orch.workflow["inputs"]) == 0

        # Nodes should no longer have condition
        for node in orch.workflow["nodes"]:
            if node["type"] == "decision":
                assert "condition" not in node

    def test_remove_variable_force_as_string_boolean(self, orchestrator_with_workflow):
        """Test that force parameter works when passed as string 'true' (MCP compatibility)."""
        orch = orchestrator_with_workflow

        # Add variable
        result1 = orch.run_tool("add_workflow_variable", {"name": "Patient Age", "type": "number"})
        assert result1.success
        var_id = result1.data["variable"]["id"]

        # Add node with condition that references the variable
        result2 = orch.run_tool("add_node", {
            "type": "decision",
            "label": "Age > 60?",
            "x": 100,
            "y": 100,
            "condition": {"input_id": var_id, "comparator": "gt", "value": 60}
        })
        assert result2.success

        # Remove variable with force as STRING "true" (simulating MCP JSON deserialization)
        result = orch.run_tool("remove_workflow_variable", {"name": "Patient Age", "force": "true"})

        print(f"\n[DEBUG] Remove with force='true' (string): {json.dumps(result.data, indent=2)}")

        # Should succeed even though force is a string
        assert result.success
        assert "Removed variable 'Patient Age'" in result.data["message"]
        assert result.data["affected_nodes"] == 1

        # Nodes should no longer have condition
        for node in orch.workflow["nodes"]:
            if node["type"] == "decision":
                assert "condition" not in node

    def test_remove_variable_multiple_references_error_shows_nodes(self, orchestrator_with_workflow):
        """Test that error message shows node labels when multiple nodes reference the variable."""
        orch = orchestrator_with_workflow

        # Add variable
        result1 = orch.run_tool("add_workflow_variable", {"name": "Blood Pressure", "type": "number"})
        assert result1.success
        var_id = result1.data["variable"]["id"]

        # Add multiple nodes with different labels and conditions
        comparators = ["gt", "lt", "eq", "gte"]
        values = [140, 90, 120, 80]
        for i, (label, comp, val) in enumerate(zip(
            ["BP > 140?", "BP < 90?", "BP Normal?", "BP Critical?"],
            comparators, values
        )):
            result = orch.run_tool("add_node", {
                "type": "decision",
                "label": label,
                "x": 100,
                "y": 100 * i,
                "condition": {"input_id": var_id, "comparator": comp, "value": val}
            })
            assert result.success

        # Try to remove without force
        result = orch.run_tool("remove_workflow_variable", {"name": "Blood Pressure"})

        print(f"\n[DEBUG] Multiple references error: {json.dumps(result.data, indent=2)}")

        # Should show first 3 node labels
        assert not result.success
        assert "referenced by 4 node(s)" in result.error
        assert "BP > 140?" in result.error
        assert "BP < 90?" in result.error
        assert "BP Normal?" in result.error
        assert "and 1 more" in result.error  # 4th node truncated


class TestDecisionNodeConditions:
    """Test decision nodes with condition references to variables."""

    def test_add_decision_node_with_condition(self, orchestrator_with_workflow):
        """Test adding a decision node that references a variable via condition."""
        orch = orchestrator_with_workflow
        
        # Register variable first
        result1 = orch.run_tool("add_workflow_variable", {"name": "Patient Age", "type": "number"})
        assert result1.success
        var_id = result1.data["variable"]["id"]

        # Add decision node with condition
        result2 = orch.run_tool("add_node", {
            "type": "decision",
            "label": "Patient Age > 60?",
            "x": 100,
            "y": 100,
            "condition": {
                "input_id": var_id,
                "comparator": "gt",
                "value": 60
            }
        })

        print(f"\n[DEBUG] Add decision node result: {json.dumps(result2.data, indent=2)}")

        assert result2.success
        assert "node" in result2.data
        assert result2.data["node"]["condition"]["input_id"] == var_id
        assert result2.data["node"]["condition"]["comparator"] == "gt"
        assert result2.data["node"]["condition"]["value"] == 60

    def test_add_decision_node_without_condition_fails(self, orchestrator_with_workflow):
        """Test that adding a decision node without condition fails."""
        orch = orchestrator_with_workflow
        
        # Try to add decision node without condition
        result = orch.run_tool("add_node", {
            "type": "decision",
            "label": "Age check",
            "x": 100,
            "y": 100
        })

        print(f"\n[DEBUG] Decision without condition result: {json.dumps(result.data, indent=2)}")

        assert not result.success
        assert "condition" in result.error.lower()

    def test_add_decision_node_with_invalid_variable_fails(self, orchestrator_with_workflow):
        """Test that referencing non-existent variable in condition fails."""
        orch = orchestrator_with_workflow
        
        # Try to reference non-existent variable
        result = orch.run_tool("add_node", {
            "type": "decision",
            "label": "Age check",
            "x": 100,
            "y": 100,
            "condition": {
                "input_id": "var_nonexistent_number",
                "comparator": "gt",
                "value": 60
            }
        })

        print(f"\n[DEBUG] Invalid variable result: {json.dumps(result.data, indent=2)}")

        assert not result.success
        assert "not found" in result.error.lower()

    def test_batch_edit_with_conditions(self, orchestrator_with_workflow):
        """Test batch_edit_workflow with decision conditions."""
        orch = orchestrator_with_workflow
        
        # Register variable first
        result1 = orch.run_tool("add_workflow_variable", {"name": "Patient Age", "type": "number"})
        assert result1.success
        var_id = result1.data["variable"]["id"]

        # Batch create decision with branches
        result = orch.run_tool("batch_edit_workflow", {
            "operations": [
                {
                    "op": "add_node",
                    "id": "temp_decision",
                    "type": "decision",
                    "label": "Patient Age > 60?",
                    "x": 100,
                    "y": 100,
                    "condition": {
                        "input_id": var_id,
                        "comparator": "gt",
                        "value": 60
                    }
                },
                {
                    "op": "add_node",
                    "id": "temp_old",
                    "type": "end",
                    "label": "Old",
                    "x": 50,
                    "y": 200
                },
                {
                    "op": "add_node",
                    "id": "temp_young",
                    "type": "end",
                    "label": "Young",
                    "x": 150,
                    "y": 200
                },
                {
                    "op": "add_connection",
                    "from": "temp_decision",
                    "to": "temp_old",
                    "label": "true"
                },
                {
                    "op": "add_connection",
                    "from": "temp_decision",
                    "to": "temp_young",
                    "label": "false"
                }
            ]
        })

        print(f"\n[DEBUG] Batch with condition result: {json.dumps(result.data, indent=2)}")

        assert result.success

        # Find the decision node
        decision_node = next(
            (n for n in result.data["workflow"]["nodes"] if n["type"] == "decision"),
            None
        )
        assert decision_node is not None
        assert decision_node["condition"]["input_id"] == var_id
        assert decision_node["condition"]["comparator"] == "gt"
        assert decision_node["condition"]["value"] == 60


class TestVariableValidation:
    """Test variable validation and error handling."""

    def test_add_variable_missing_name(self, orchestrator_with_workflow):
        """Test that missing name is rejected."""
        orch = orchestrator_with_workflow
        
        result = orch.run_tool("add_workflow_variable", {"type": "number"})

        assert not result.success
        assert "name" in result.error.lower()

    def test_add_variable_invalid_type(self, orchestrator_with_workflow):
        """Test that invalid type is rejected."""
        orch = orchestrator_with_workflow
        
        result = orch.run_tool("add_workflow_variable", {"name": "Test", "type": "invalid_type"})

        assert not result.success
        assert "type" in result.error.lower()

    def test_enum_variable_requires_values(self, orchestrator_with_workflow):
        """Test that enum type requires enum_values."""
        orch = orchestrator_with_workflow
        
        result = orch.run_tool("add_workflow_variable", {"name": "Test", "type": "enum"})

        assert not result.success
        assert "enum_values" in result.error.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
