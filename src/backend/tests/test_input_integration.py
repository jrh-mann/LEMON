"""Integration tests for workflow variable management.

Tests the complete flow from tool call to orchestrator state update.
Focuses on potential bugs:
1. Double-append bug (variables added twice)
2. Multiple variables handling
3. State synchronization between tool and orchestrator

After the DB-as-single-source-of-truth refactor, the orchestrator refreshes
its in-memory state from the database after each tool call instead of
manually syncing from tool result dicts.
"""

from __future__ import annotations

import json

import pytest

from ..tools.workflow_input import AddWorkflowVariableTool


class TestVariableDoubleAppendBug:
    """Test for the double-append bug where variables are added twice."""

    def test_add_variable_not_duplicated_in_orchestrator(self, orchestrator_with_workflow):
        """Test that adding a variable doesn't create duplicates in orchestrator state.

        With DB-as-source-of-truth, the tool saves to DB and the orchestrator
        refreshes from DB. No manual sync means no double-append risk.
        """
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

        # Execute tool directly (saves to DB)
        result = tool.execute(
            {"name": "Patient Age", "type": "number"},
            session_state=session_state
        )

        assert result["success"] is True

        # Simulate what orchestrator.run_tool now does: refresh from DB
        orch.refresh_workflow_from_db()

        # Check for duplicates - DB refresh guarantees exactly what's in DB
        variables = orch.workflow["variables"]
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

            # Simulate what orchestrator.run_tool now does: refresh from DB
            orch.refresh_workflow_from_db()

        # Should have exactly 3 variables, no duplicates
        variables = orch.workflow["variables"]
        assert len(variables) == 3, f"Expected 3 variables, got {len(variables)}: {variables}"

        var_names_result = [var["name"] for var in variables]
        assert var_names_result == var_names


class TestVariableStateSync:
    """Test state synchronization between tool and orchestrator."""

    def test_tool_returns_workflow_analysis_for_sync(self, orchestrator_with_workflow):
        """Test that tool returns workflow_analysis in its result.

        Tools still return workflow_analysis for MCP compatibility and for
        ws_chat event emissions, but the orchestrator now reads from DB
        instead of parsing these return values.
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

        assert result["success"] is True

        # Tool should still return workflow_analysis (used by ws_chat emissions)
        assert "workflow_analysis" in result, "Tool must return workflow_analysis for ws_chat"
        assert "variables" in result["workflow_analysis"]
        assert len(result["workflow_analysis"]["variables"]) == 1
        assert result["workflow_analysis"]["variables"][0]["name"] == "Patient Age"

        # After orchestrator refreshes from DB, state should match
        orch.refresh_workflow_from_db()
        assert len(orch.workflow["variables"]) == 1
        assert orch.workflow["variables"][0]["name"] == "Patient Age"

    def test_orchestrator_run_tool_updates_state(self, orchestrator_with_workflow):
        """Test that orchestrator.run_tool properly updates workflow state via DB refresh."""
        orch = orchestrator_with_workflow

        # Run tool through orchestrator
        result = orch.run_tool(
            "add_workflow_variable",
            {"name": "Patient Age", "type": "number"}
        )

        assert result.data["success"] is True

        # Check orchestrator state was updated (via refresh_workflow_from_db in run_tool)
        variables = orch.workflow["variables"]

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
        assert result1.data["success"] is True

        # Add second variable
        result2 = orch.run_tool(
            "add_workflow_variable",
            {"name": "Blood Glucose", "type": "number"}
        )
        assert result2.data["success"] is True

        # Add third variable
        result3 = orch.run_tool(
            "add_workflow_variable",
            {"name": "Patient Gender", "type": "enum", "enum_values": ["Male", "Female", "Other"]}
        )
        assert result3.data["success"] is True

        # Verify final state
        variables = orch.workflow["variables"]

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
        assert node_result.data["success"] is True
        assert node_result.data["node"]["condition"]["input_id"] == var_id

        # Verify orchestrator state
        assert len(orch.workflow["variables"]) == 1
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

        # Verify no duplicates
        assert len(orch.workflow["variables"]) == 2
        assert len(orch.current_workflow["nodes"]) == 2

        # Verify conditions reference correct variables
        nodes = orch.current_workflow["nodes"]
        assert nodes[0]["condition"]["input_id"] == age_id
        assert nodes[1]["condition"]["input_id"] == glucose_id


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
