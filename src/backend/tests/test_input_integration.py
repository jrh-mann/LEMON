"""Integration tests for workflow variable management.

Tests the complete flow from tool call to orchestrator state update.
Focuses on potential bugs:
1. Double-append bug (variables added twice)
2. Multiple variables handling
3. State synchronization between tool and orchestrator
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from ..agents.orchestrator_factory import build_orchestrator
from ..storage.workflows import WorkflowStore
from ..tools.workflow_input import AddWorkflowVariableTool


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
        "description": "Test workflow for input integration tests",
        "output_type": "string"
    })
    
    assert result.success, f"Failed to create test workflow: {result.error}"
    
    # Set current_workflow_id to the newly created workflow
    workflow_id = result.data.get("workflow_id")
    assert workflow_id, "create_workflow did not return workflow_id"
    orch.current_workflow_id = workflow_id
    
    return orch


class TestVariableDoubleAppendBug:
    """Test for the double-append bug where variables are added twice."""

    def test_add_variable_not_duplicated_in_orchestrator(self, orchestrator_with_workflow):
        """Test that adding a variable doesn't create duplicates in orchestrator state."""
        orch = orchestrator_with_workflow

        tool = AddWorkflowVariableTool()

        # Build session_state the same way orchestrator.run_tool does
        session_state = {
            "workflow_analysis": orch.workflow_analysis,
            "current_workflow": orch.current_workflow,
            "current_workflow_id": orch.current_workflow_id,
            "workflow_store": orch.workflow_store,
            "user_id": orch.user_id,
        }

        # Execute tool directly
        result = tool.execute(
            {"name": "Patient Age", "type": "number"},
            session_state=session_state
        )

        print(f"\n[DEBUG] Tool result: {json.dumps(result, indent=2)}")
        print(f"[DEBUG] Orchestrator variables BEFORE update: {orch.workflow['inputs']}")

        assert result["success"] is True

        # Simulate what orchestrator.run_tool does
        orch._update_analysis_from_tool_result("add_workflow_variable", result)

        print(f"[DEBUG] Orchestrator variables AFTER update: {orch.workflow['inputs']}")

        # Check for duplicates - this will fail if double-append bug exists
        variables = orch.workflow["inputs"]
        assert len(variables) == 1, f"Expected 1 variable, got {len(variables)}: {variables}"
        assert variables[0]["name"] == "Patient Age"

    def test_multiple_variables_no_duplicates(self, orchestrator_with_workflow):
        """Test that adding multiple variables doesn't create duplicates."""
        orch = orchestrator_with_workflow

        tool = AddWorkflowVariableTool()

        # Add 3 variables
        var_names = ["Patient Age", "Blood Glucose", "Heart Rate"]

        for name in var_names:
            session_state = {
                "workflow_analysis": orch.workflow_analysis,
                "current_workflow": orch.current_workflow,
                "current_workflow_id": orch.current_workflow_id,
                "workflow_store": orch.workflow_store,
                "user_id": orch.user_id,
            }
            
            result = tool.execute(
                {"name": name, "type": "number"},
                session_state=session_state
            )
            assert result["success"] is True

            # Simulate orchestrator update
            orch._update_analysis_from_tool_result("add_workflow_variable", result)

        print(f"\n[DEBUG] Final variables: {json.dumps(orch.workflow['inputs'], indent=2)}")

        # Should have exactly 3 variables, no duplicates
        variables = orch.workflow["inputs"]
        assert len(variables) == 3, f"Expected 3 variables, got {len(variables)}: {variables}"

        var_names_result = [var["name"] for var in variables]
        assert var_names_result == var_names


class TestVariableStateSync:
    """Test state synchronization between tool and orchestrator."""

    def test_tool_returns_workflow_analysis_for_sync(self, orchestrator_with_workflow):
        """Test that tool returns workflow_analysis for orchestrator to sync.
        
        With the multi-workflow architecture, tools save to database and return
        workflow_analysis in their response. The orchestrator syncs this back
        via _update_analysis_from_tool_result().
        """
        orch = orchestrator_with_workflow

        tool = AddWorkflowVariableTool()

        # Execute tool with orchestrator's workflow_analysis as session_state
        session_state = {
            "workflow_analysis": orch.workflow_analysis,
            "current_workflow": orch.current_workflow,
            "current_workflow_id": orch.current_workflow_id,
            "workflow_store": orch.workflow_store,
            "user_id": orch.user_id,
        }

        result = tool.execute(
            {"name": "Patient Age", "type": "number"},
            session_state=session_state
        )

        print(f"\n[DEBUG] Tool result: {result}")

        assert result["success"] is True

        # Tool should return workflow_analysis for orchestrator sync
        assert "workflow_analysis" in result, "Tool must return workflow_analysis for sync"
        assert "variables" in result["workflow_analysis"]
        assert len(result["workflow_analysis"]["variables"]) == 1
        assert result["workflow_analysis"]["variables"][0]["name"] == "Patient Age"

        # After orchestrator syncs, state should be updated
        orch._update_analysis_from_tool_result("add_workflow_variable", result)
        assert len(orch.workflow["inputs"]) == 1
        assert orch.workflow["inputs"][0]["name"] == "Patient Age"

    def test_orchestrator_run_tool_updates_state(self, orchestrator_with_workflow):
        """Test that orchestrator.run_tool properly updates workflow_analysis."""
        orch = orchestrator_with_workflow

        # Run tool through orchestrator
        result = orch.run_tool(
            "add_workflow_variable",
            {"name": "Patient Age", "type": "number"}
        )

        print(f"\n[DEBUG] Run tool result: {json.dumps(result.data, indent=2)}")
        print(f"[DEBUG] Orchestrator variables: {orch.workflow['inputs']}")

        assert result.data["success"] is True

        # Check orchestrator state was updated
        variables = orch.workflow["inputs"]

        # This will fail if there's a double-append bug
        assert len(variables) == 1, f"Expected 1 variable, got {len(variables)}: {variables}"
        assert variables[0]["name"] == "Patient Age"


class TestVariableToolSequence:
    """Test calling variable tools multiple times in sequence."""

    def test_add_multiple_variables_via_run_tool(self, orchestrator_with_workflow):
        """Test adding multiple variables through orchestrator.run_tool."""
        orch = orchestrator_with_workflow

        # Add first variable
        result1 = orch.run_tool(
            "add_workflow_variable",
            {"name": "Patient Age", "type": "number"}
        )
        print(f"\n[DEBUG] After variable 1: {orch.workflow['inputs']}")
        assert result1.data["success"] is True

        # Add second variable
        result2 = orch.run_tool(
            "add_workflow_variable",
            {"name": "Blood Glucose", "type": "number"}
        )
        print(f"[DEBUG] After variable 2: {orch.workflow['inputs']}")
        assert result2.data["success"] is True

        # Add third variable
        result3 = orch.run_tool(
            "add_workflow_variable",
            {"name": "Patient Gender", "type": "enum", "enum_values": ["Male", "Female", "Other"]}
        )
        print(f"[DEBUG] After variable 3: {orch.workflow['inputs']}")
        assert result3.data["success"] is True

        # Verify final state
        variables = orch.workflow["inputs"]
        print(f"\n[DEBUG] Final variables: {json.dumps(variables, indent=2)}")

        assert len(variables) == 3, f"Expected 3 variables, got {len(variables)}"

        names = [var["name"] for var in variables]
        assert names == ["Patient Age", "Blood Glucose", "Patient Gender"]

    def test_add_then_list_variables(self, orchestrator_with_workflow):
        """Test that list_workflow_variables returns correct data after adds."""
        orch = orchestrator_with_workflow

        # Add variables
        orch.run_tool("add_workflow_variable", {"name": "Patient Age", "type": "number"})
        orch.run_tool("add_workflow_variable", {"name": "Blood Glucose", "type": "number"})

        # List variables
        result = orch.run_tool("list_workflow_variables", {})

        print(f"\n[DEBUG] List result: {json.dumps(result.data, indent=2)}")

        assert result.data["success"] is True
        assert result.data["count"] == 2
        assert len(result.data["variables"]) == 2

        names = [var["name"] for var in result.data["variables"]]
        assert "Patient Age" in names
        assert "Blood Glucose" in names


class TestVariableAndNodeLinking:
    """Test the complete flow of adding variables and creating decision nodes with conditions."""

    def test_add_variable_then_decision_with_condition(self, orchestrator_with_workflow):
        """Test adding variable then creating decision node that references it."""
        orch = orchestrator_with_workflow

        # Add variable
        input_result = orch.run_tool(
            "add_workflow_variable",
            {"name": "Patient Age", "type": "number"}
        )
        print(f"\n[DEBUG] Variable result: {json.dumps(input_result.data, indent=2)}")
        assert input_result.data["success"] is True
        var_id = input_result.data["variable"]["id"]

        # Add decision node with condition that references the variable
        node_result = orch.run_tool(
            "add_node",
            {
                "type": "decision",
                "label": "Patient over 60?",
                "x": 100,
                "y": 100,
                "condition": {
                    "input_id": var_id,
                    "comparator": "gt",
                    "value": 60
                }
            }
        )
        print(f"\n[DEBUG] Node result: {json.dumps(node_result.data, indent=2)}")
        assert node_result.data["success"] is True
        assert node_result.data["node"]["condition"]["input_id"] == var_id

        # Verify orchestrator state
        assert len(orch.workflow["inputs"]) == 1
        assert len(orch.current_workflow["nodes"]) == 1
        assert orch.current_workflow["nodes"][0]["condition"]["input_id"] == var_id

    def test_multiple_variables_multiple_decisions(self, orchestrator_with_workflow):
        """Test adding multiple variables and decision nodes that reference them."""
        orch = orchestrator_with_workflow

        # Add variables
        age_result = orch.run_tool("add_workflow_variable", {"name": "Patient Age", "type": "number"})
        glucose_result = orch.run_tool("add_workflow_variable", {"name": "Blood Glucose", "type": "number"})
        
        assert age_result.success, f"Failed to add age variable: {age_result.error}"
        assert glucose_result.success, f"Failed to add glucose variable: {glucose_result.error}"
        
        age_id = age_result.data["variable"]["id"]
        glucose_id = glucose_result.data["variable"]["id"]

        # Add decision nodes with conditions
        orch.run_tool(
            "add_node",
            {
                "type": "decision",
                "label": "Age > 60?",
                "x": 100,
                "y": 100,
                "condition": {"input_id": age_id, "comparator": "gt", "value": 60}
            }
        )
        orch.run_tool(
            "add_node",
            {
                "type": "decision",
                "label": "Glucose > 140?",
                "x": 100,
                "y": 200,
                "condition": {"input_id": glucose_id, "comparator": "gt", "value": 140}
            }
        )

        print(f"\n[DEBUG] Final variables: {orch.workflow['inputs']}")
        print(f"[DEBUG] Final nodes: {orch.current_workflow['nodes']}")

        # Verify no duplicates
        assert len(orch.workflow["inputs"]) == 2
        assert len(orch.current_workflow["nodes"]) == 2

        # Verify conditions reference correct variables
        nodes = orch.current_workflow["nodes"]
        assert nodes[0]["condition"]["input_id"] == age_id
        assert nodes[1]["condition"]["input_id"] == glucose_id


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
