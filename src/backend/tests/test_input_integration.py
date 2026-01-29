"""Integration tests for workflow variable management.

Tests the complete flow from tool call to orchestrator state update.
Focuses on potential bugs:
1. Double-append bug (variables added twice)
2. Multiple variables handling
3. State synchronization between tool and orchestrator
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

import pytest

from ..agents.orchestrator_factory import build_orchestrator
from ..api.conversations import ConversationStore


# Disable MCP for these tests to ensure direct tool execution
@pytest.fixture(autouse=True)
def disable_mcp(monkeypatch):
    """Disable MCP mode for all tests in this module."""
    monkeypatch.setenv("LEMON_USE_MCP", "false")


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


class TestVariableDoubleAppendBug:
    """Test for the double-append bug where variables are added twice."""

    def test_add_variable_not_duplicated_in_orchestrator(self, conversation_store, conversation_id):
        """Test that adding a variable doesn't create duplicates in orchestrator state."""
        from ..tools.workflow_input import AddWorkflowInputTool

        convo = conversation_store.get_or_create(conversation_id)
        orchestrator = convo.orchestrator

        # Ensure workflow_analysis is initialized
        orchestrator.workflow_analysis = {"variables": [], "outputs": []}

        tool = AddWorkflowInputTool()

        # Execute tool through orchestrator's session_state
        result = tool.execute(
            {"name": "Patient Age", "type": "number"},
            session_state={
                "workflow_analysis": orchestrator.workflow_analysis,
                "current_workflow": orchestrator.current_workflow,
            }
        )

        print(f"\n[DEBUG] Tool result: {json.dumps(result, indent=2)}")
        print(f"[DEBUG] Orchestrator variables BEFORE update: {orchestrator.workflow_analysis.get('variables', [])}")

        assert result["success"] is True

        # Simulate what orchestrator.run_tool does
        if result.get("success"):
            orchestrator._update_analysis_from_tool_result("add_workflow_variable", result)

        print(f"[DEBUG] Orchestrator variables AFTER update: {orchestrator.workflow_analysis.get('variables', [])}")

        # Check for duplicates - this will fail if double-append bug exists
        # Note: Storage uses 'inputs' key internally
        variables = orchestrator.workflow["inputs"]
        assert len(variables) == 1, f"Expected 1 variable, got {len(variables)}: {variables}"
        assert variables[0]["name"] == "Patient Age"

    def test_multiple_variables_no_duplicates(self, conversation_store, conversation_id):
        """Test that adding multiple variables doesn't create duplicates."""
        from ..tools.workflow_input import AddWorkflowInputTool

        convo = conversation_store.get_or_create(conversation_id)
        orchestrator = convo.orchestrator
        orchestrator.workflow_analysis = {"variables": [], "outputs": []}

        tool = AddWorkflowInputTool()

        # Add 3 variables
        var_names = ["Patient Age", "Blood Glucose", "Patient Gender"]

        for name in var_names:
            result = tool.execute(
                {"name": name, "type": "number"},
                session_state={
                    "workflow_analysis": orchestrator.workflow_analysis,
                    "current_workflow": orchestrator.current_workflow,
                }
            )
            assert result["success"] is True

            # Simulate orchestrator update
            orchestrator._update_analysis_from_tool_result("add_workflow_variable", result)

        print(f"\n[DEBUG] Final variables: {json.dumps(orchestrator.workflow['inputs'], indent=2)}")

        # Should have exactly 3 variables, no duplicates
        variables = orchestrator.workflow["inputs"]
        assert len(variables) == 3, f"Expected 3 variables, got {len(variables)}: {variables}"

        var_names_result = [var["name"] for var in variables]
        assert var_names_result == var_names


class TestVariableStateSync:
    """Test state synchronization between tool and orchestrator."""

    def test_tool_modifies_session_state_directly(self, conversation_store, conversation_id):
        """Test that tool modifies session_state dict (not a copy)."""
        from ..tools.workflow_input import AddWorkflowInputTool

        convo = conversation_store.get_or_create(conversation_id)
        orchestrator = convo.orchestrator

        tool = AddWorkflowInputTool()

        # Execute tool with orchestrator's workflow_analysis as session_state
        session_state = {
            "workflow_analysis": orchestrator.workflow_analysis,
            "current_workflow": orchestrator.current_workflow,
        }

        result = tool.execute(
            {"name": "Patient Age", "type": "number"},
            session_state=session_state
        )

        print(f"\n[DEBUG] Tool result: {result}")
        print(f"[DEBUG] Session state after tool: {session_state['workflow_analysis']}")
        print(f"[DEBUG] Orchestrator state: {orchestrator.workflow_analysis}")

        assert result["success"] is True

        # The tool should have modified the session_state dict directly
        # Since session_state["workflow_analysis"] IS orchestrator.workflow_analysis,
        # the orchestrator's state should already be updated
        assert len(orchestrator.workflow["inputs"]) == 1, \
            "Tool should modify session_state dict directly"
        assert orchestrator.workflow["inputs"][0]["name"] == "Patient Age"

    def test_orchestrator_run_tool_updates_state(self, conversation_store, conversation_id):
        """Test that orchestrator.run_tool properly updates workflow_analysis."""
        convo = conversation_store.get_or_create(conversation_id)
        orchestrator = convo.orchestrator

        # Clear state
        orchestrator.workflow_analysis = {"variables": [], "outputs": []}

        # Run tool through orchestrator
        result = orchestrator.run_tool(
            "add_workflow_variable",
            {"name": "Patient Age", "type": "number"}
        )

        print(f"\n[DEBUG] Run tool result: {json.dumps(result.data, indent=2)}")
        print(f"[DEBUG] Orchestrator variables: {orchestrator.workflow['inputs']}")

        assert result.data["success"] is True

        # Check orchestrator state was updated
        variables = orchestrator.workflow["inputs"]

        # This will fail if there's a double-append bug
        assert len(variables) == 1, f"Expected 1 variable, got {len(variables)}: {variables}"
        assert variables[0]["name"] == "Patient Age"


class TestVariableToolSequence:
    """Test calling variable tools multiple times in sequence."""

    def test_add_multiple_variables_via_run_tool(self, conversation_store, conversation_id):
        """Test adding multiple variables through orchestrator.run_tool."""
        convo = conversation_store.get_or_create(conversation_id)
        orchestrator = convo.orchestrator
        orchestrator.workflow_analysis = {"variables": [], "outputs": []}

        # Add first variable
        result1 = orchestrator.run_tool(
            "add_workflow_variable",
            {"name": "Patient Age", "type": "number"}
        )
        print(f"\n[DEBUG] After variable 1: {orchestrator.workflow['inputs']}")
        assert result1.data["success"] is True

        # Add second variable
        result2 = orchestrator.run_tool(
            "add_workflow_variable",
            {"name": "Blood Glucose", "type": "number"}
        )
        print(f"[DEBUG] After variable 2: {orchestrator.workflow['inputs']}")
        assert result2.data["success"] is True

        # Add third variable
        result3 = orchestrator.run_tool(
            "add_workflow_variable",
            {"name": "Patient Gender", "type": "enum", "enum_values": ["Male", "Female", "Other"]}
        )
        print(f"[DEBUG] After variable 3: {orchestrator.workflow['inputs']}")
        assert result3.data["success"] is True

        # Verify final state
        variables = orchestrator.workflow["inputs"]
        print(f"\n[DEBUG] Final variables: {json.dumps(variables, indent=2)}")

        assert len(variables) == 3, f"Expected 3 variables, got {len(variables)}"

        names = [var["name"] for var in variables]
        assert names == ["Patient Age", "Blood Glucose", "Patient Gender"]

    def test_add_then_list_variables(self, conversation_store, conversation_id):
        """Test that list_workflow_variables returns correct data after adds."""
        convo = conversation_store.get_or_create(conversation_id)
        orchestrator = convo.orchestrator
        orchestrator.workflow_analysis = {"variables": [], "outputs": []}

        # Add variables
        orchestrator.run_tool("add_workflow_variable", {"name": "Patient Age", "type": "number"})
        orchestrator.run_tool("add_workflow_variable", {"name": "Blood Glucose", "type": "number"})

        # List variables
        result = orchestrator.run_tool("list_workflow_variables", {})

        print(f"\n[DEBUG] List result: {json.dumps(result.data, indent=2)}")

        assert result.data["success"] is True
        assert result.data["count"] == 2
        assert len(result.data["variables"]) == 2

        names = [var["name"] for var in result.data["variables"]]
        assert "Patient Age" in names
        assert "Blood Glucose" in names


class TestVariableAndNodeLinking:
    """Test the complete flow of adding variables and creating decision nodes with conditions."""

    def test_add_variable_then_decision_with_condition(self, conversation_store, conversation_id):
        """Test adding variable then creating decision node that references it."""
        convo = conversation_store.get_or_create(conversation_id)
        orchestrator = convo.orchestrator
        orchestrator.workflow_analysis = {"variables": [], "outputs": []}
        orchestrator.current_workflow = {"nodes": [], "edges": []}

        # Add variable
        input_result = orchestrator.run_tool(
            "add_workflow_variable",
            {"name": "Patient Age", "type": "int"}
        )
        print(f"\n[DEBUG] Variable result: {json.dumps(input_result.data, indent=2)}")
        assert input_result.data["success"] is True
        var_id = input_result.data["variable"]["id"]

        # Add decision node with condition that references the variable
        node_result = orchestrator.run_tool(
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
        assert len(orchestrator.workflow["inputs"]) == 1
        assert len(orchestrator.current_workflow["nodes"]) == 1
        assert orchestrator.current_workflow["nodes"][0]["condition"]["input_id"] == var_id

    def test_multiple_variables_multiple_decisions(self, conversation_store, conversation_id):
        """Test adding multiple variables and decision nodes that reference them."""
        convo = conversation_store.get_or_create(conversation_id)
        orchestrator = convo.orchestrator
        orchestrator.workflow_analysis = {"variables": [], "outputs": []}
        orchestrator.current_workflow = {"nodes": [], "edges": []}

        # Add variables
        age_result = orchestrator.run_tool("add_workflow_variable", {"name": "Patient Age", "type": "int"})
        glucose_result = orchestrator.run_tool("add_workflow_variable", {"name": "Blood Glucose", "type": "int"})
        age_id = age_result.data["variable"]["id"]
        glucose_id = glucose_result.data["variable"]["id"]

        # Add decision nodes with conditions
        orchestrator.run_tool(
            "add_node",
            {
                "type": "decision",
                "label": "Age > 60?",
                "x": 100,
                "y": 100,
                "condition": {"input_id": age_id, "comparator": "gt", "value": 60}
            }
        )
        orchestrator.run_tool(
            "add_node",
            {
                "type": "decision",
                "label": "Glucose > 140?",
                "x": 100,
                "y": 200,
                "condition": {"input_id": glucose_id, "comparator": "gt", "value": 140}
            }
        )

        print(f"\n[DEBUG] Final variables: {orchestrator.workflow['inputs']}")
        print(f"[DEBUG] Final nodes: {orchestrator.current_workflow['nodes']}")

        # Verify no duplicates
        assert len(orchestrator.workflow["inputs"]) == 2
        assert len(orchestrator.current_workflow["nodes"]) == 2

        # Verify conditions reference correct variables
        nodes = orchestrator.current_workflow["nodes"]
        assert nodes[0]["condition"]["input_id"] == age_id
        assert nodes[1]["condition"]["input_id"] == glucose_id


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
