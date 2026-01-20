"""Integration tests for workflow input management.

Tests the complete flow from tool call to orchestrator state update.
Focuses on potential bugs:
1. Double-append bug (inputs added twice)
2. Multiple inputs handling
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


class TestInputDoubleAppendBug:
    """Test for the double-append bug where inputs are added twice."""

    def test_add_input_not_duplicated_in_orchestrator(self, conversation_store, conversation_id):
        """Test that adding an input doesn't create duplicates in orchestrator state."""
        from ..tools.workflow_input import AddWorkflowInputTool

        convo = conversation_store.get_or_create(conversation_id)
        orchestrator = convo.orchestrator

        # Ensure workflow_analysis is initialized
        orchestrator.workflow_analysis = {"inputs": [], "outputs": []}

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
        print(f"[DEBUG] Orchestrator inputs BEFORE update: {orchestrator.workflow_analysis['inputs']}")

        assert result["success"] is True

        # Simulate what orchestrator.run_tool does
        if result.get("success"):
            orchestrator._update_analysis_from_tool_result("add_workflow_input", result)

        print(f"[DEBUG] Orchestrator inputs AFTER update: {orchestrator.workflow_analysis['inputs']}")

        # Check for duplicates - this will fail if double-append bug exists
        inputs = orchestrator.workflow_analysis["inputs"]
        assert len(inputs) == 1, f"Expected 1 input, got {len(inputs)}: {inputs}"
        assert inputs[0]["name"] == "Patient Age"

    def test_multiple_inputs_no_duplicates(self, conversation_store, conversation_id):
        """Test that adding multiple inputs doesn't create duplicates."""
        from ..tools.workflow_input import AddWorkflowInputTool

        convo = conversation_store.get_or_create(conversation_id)
        orchestrator = convo.orchestrator
        orchestrator.workflow_analysis = {"inputs": [], "outputs": []}

        tool = AddWorkflowInputTool()

        # Add 3 inputs
        input_names = ["Patient Age", "Blood Glucose", "Patient Gender"]

        for name in input_names:
            result = tool.execute(
                {"name": name, "type": "number"},
                session_state={
                    "workflow_analysis": orchestrator.workflow_analysis,
                    "current_workflow": orchestrator.current_workflow,
                }
            )
            assert result["success"] is True

            # Simulate orchestrator update
            orchestrator._update_analysis_from_tool_result("add_workflow_input", result)

        print(f"\n[DEBUG] Final inputs: {json.dumps(orchestrator.workflow_analysis['inputs'], indent=2)}")

        # Should have exactly 3 inputs, no duplicates
        inputs = orchestrator.workflow_analysis["inputs"]
        assert len(inputs) == 3, f"Expected 3 inputs, got {len(inputs)}: {inputs}"

        input_names_result = [inp["name"] for inp in inputs]
        assert input_names_result == input_names


class TestInputStateSync:
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
        assert len(orchestrator.workflow_analysis["inputs"]) == 1, \
            "Tool should modify session_state dict directly"
        assert orchestrator.workflow_analysis["inputs"][0]["name"] == "Patient Age"

    def test_orchestrator_run_tool_updates_state(self, conversation_store, conversation_id):
        """Test that orchestrator.run_tool properly updates workflow_analysis."""
        convo = conversation_store.get_or_create(conversation_id)
        orchestrator = convo.orchestrator

        # Clear state
        orchestrator.workflow_analysis = {"inputs": [], "outputs": []}

        # Run tool through orchestrator
        result = orchestrator.run_tool(
            "add_workflow_input",
            {"name": "Patient Age", "type": "number"}
        )

        print(f"\n[DEBUG] Run tool result: {json.dumps(result.data, indent=2)}")
        print(f"[DEBUG] Orchestrator inputs: {orchestrator.workflow_analysis['inputs']}")

        assert result.data["success"] is True

        # Check orchestrator state was updated
        inputs = orchestrator.workflow_analysis["inputs"]

        # This will fail if there's a double-append bug
        assert len(inputs) == 1, f"Expected 1 input, got {len(inputs)}: {inputs}"
        assert inputs[0]["name"] == "Patient Age"


class TestInputToolSequence:
    """Test calling input tools multiple times in sequence."""

    def test_add_multiple_inputs_via_run_tool(self, conversation_store, conversation_id):
        """Test adding multiple inputs through orchestrator.run_tool."""
        convo = conversation_store.get_or_create(conversation_id)
        orchestrator = convo.orchestrator
        orchestrator.workflow_analysis = {"inputs": [], "outputs": []}

        # Add first input
        result1 = orchestrator.run_tool(
            "add_workflow_input",
            {"name": "Patient Age", "type": "number"}
        )
        print(f"\n[DEBUG] After input 1: {orchestrator.workflow_analysis['inputs']}")
        assert result1.data["success"] is True

        # Add second input
        result2 = orchestrator.run_tool(
            "add_workflow_input",
            {"name": "Blood Glucose", "type": "number"}
        )
        print(f"[DEBUG] After input 2: {orchestrator.workflow_analysis['inputs']}")
        assert result2.data["success"] is True

        # Add third input
        result3 = orchestrator.run_tool(
            "add_workflow_input",
            {"name": "Patient Gender", "type": "enum", "enum_values": ["Male", "Female", "Other"]}
        )
        print(f"[DEBUG] After input 3: {orchestrator.workflow_analysis['inputs']}")
        assert result3.data["success"] is True

        # Verify final state
        inputs = orchestrator.workflow_analysis["inputs"]
        print(f"\n[DEBUG] Final inputs: {json.dumps(inputs, indent=2)}")

        assert len(inputs) == 3, f"Expected 3 inputs, got {len(inputs)}"

        names = [inp["name"] for inp in inputs]
        assert names == ["Patient Age", "Blood Glucose", "Patient Gender"]

    def test_add_then_list_inputs(self, conversation_store, conversation_id):
        """Test that list_workflow_inputs returns correct data after adds."""
        convo = conversation_store.get_or_create(conversation_id)
        orchestrator = convo.orchestrator
        orchestrator.workflow_analysis = {"inputs": [], "outputs": []}

        # Add inputs
        orchestrator.run_tool("add_workflow_input", {"name": "Patient Age", "type": "number"})
        orchestrator.run_tool("add_workflow_input", {"name": "Blood Glucose", "type": "number"})

        # List inputs
        result = orchestrator.run_tool("list_workflow_inputs", {})

        print(f"\n[DEBUG] List result: {json.dumps(result.data, indent=2)}")

        assert result.data["success"] is True
        assert result.data["count"] == 2
        assert len(result.data["inputs"]) == 2

        names = [inp["name"] for inp in result.data["inputs"]]
        assert "Patient Age" in names
        assert "Blood Glucose" in names


class TestInputAndNodeLinking:
    """Test the complete flow of adding inputs and linking nodes."""

    def test_add_input_then_node_with_ref(self, conversation_store, conversation_id):
        """Test adding input then creating node that references it."""
        convo = conversation_store.get_or_create(conversation_id)
        orchestrator = convo.orchestrator
        orchestrator.workflow_analysis = {"inputs": [], "outputs": []}
        orchestrator.current_workflow = {"nodes": [], "edges": []}

        # Add input
        input_result = orchestrator.run_tool(
            "add_workflow_input",
            {"name": "Patient Age", "type": "number"}
        )
        print(f"\n[DEBUG] Input result: {json.dumps(input_result.data, indent=2)}")
        assert input_result.data["success"] is True

        # Add node that references the input
        node_result = orchestrator.run_tool(
            "add_node",
            {
                "type": "decision",
                "label": "Patient over 60?",
                "input_ref": "Patient Age",
                "x": 100,
                "y": 100
            }
        )
        print(f"\n[DEBUG] Node result: {json.dumps(node_result.data, indent=2)}")
        assert node_result.data["success"] is True
        assert node_result.data["node"]["input_ref"] == "Patient Age"

        # Verify orchestrator state
        assert len(orchestrator.workflow_analysis["inputs"]) == 1
        assert len(orchestrator.current_workflow["nodes"]) == 1
        assert orchestrator.current_workflow["nodes"][0]["input_ref"] == "Patient Age"

    def test_multiple_inputs_multiple_nodes(self, conversation_store, conversation_id):
        """Test adding multiple inputs and nodes that reference them."""
        convo = conversation_store.get_or_create(conversation_id)
        orchestrator = convo.orchestrator
        orchestrator.workflow_analysis = {"inputs": [], "outputs": []}
        orchestrator.current_workflow = {"nodes": [], "edges": []}

        # Add inputs
        orchestrator.run_tool("add_workflow_input", {"name": "Patient Age", "type": "number"})
        orchestrator.run_tool("add_workflow_input", {"name": "Blood Glucose", "type": "number"})

        # Add nodes
        orchestrator.run_tool(
            "add_node",
            {"type": "decision", "label": "Age > 60?", "input_ref": "Patient Age", "x": 100, "y": 100}
        )
        orchestrator.run_tool(
            "add_node",
            {"type": "decision", "label": "Glucose > 140?", "input_ref": "Blood Glucose", "x": 100, "y": 200}
        )

        print(f"\n[DEBUG] Final inputs: {orchestrator.workflow_analysis['inputs']}")
        print(f"[DEBUG] Final nodes: {orchestrator.current_workflow['nodes']}")

        # Verify no duplicates
        assert len(orchestrator.workflow_analysis["inputs"]) == 2
        assert len(orchestrator.current_workflow["nodes"]) == 2

        # Verify references
        nodes = orchestrator.current_workflow["nodes"]
        assert nodes[0]["input_ref"] == "Patient Age"
        assert nodes[1]["input_ref"] == "Blood Glucose"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
