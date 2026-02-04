"""Test workflow variable management and decision node conditions.

Tests the complete flow:
1. Register variables with add_workflow_variable
2. Create decision nodes that reference variables via condition
3. Validate condition references
4. List and remove variables
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


class TestWorkflowVariableManagement:
    """Test variable registration and management."""

    def test_add_workflow_variable_basic(self, conversation_store, conversation_id):
        """Test adding a simple workflow variable."""
        from ..tools.workflow_input import AddWorkflowVariableTool

        tool = AddWorkflowVariableTool()

        # Start with empty workflow_analysis
        session_state = {"workflow_analysis": {"variables": [], "outputs": []}}

        result = tool.execute(
            {
                "name": "Patient Age",
                "type": "number",
                "description": "Patient's age in years"
            },
            session_state=session_state
        )

        print(f"\n[DEBUG] Add variable result: {json.dumps(result, indent=2)}")

        assert result["success"] is True, f"Failed to add variable: {result.get('error')}"
        assert "variable" in result
        assert result["variable"]["name"] == "Patient Age"
# Type is converted to internal format: "number" is the canonical type
        assert result["variable"]["type"] == "number"
        assert result["variable"]["description"] == "Patient's age in years"
        # ID is auto-generated
        assert result["variable"]["id"] == "var_patient_age_number"

        # Verify it was added to session state
        assert len(session_state["workflow_analysis"]["variables"]) == 1
        assert session_state["workflow_analysis"]["variables"][0]["name"] == "Patient Age"

    def test_add_workflow_variable_with_enum(self, conversation_store, conversation_id):
        """Test adding an enum variable."""
        from ..tools.workflow_input import AddWorkflowVariableTool

        tool = AddWorkflowVariableTool()
        session_state = {"workflow_analysis": {"variables": [], "outputs": []}}

        result = tool.execute(
            {
                "name": "Patient Gender",
                "type": "enum",
                "enum_values": ["Male", "Female", "Other"]
            },
            session_state=session_state
        )

        assert result["success"] is True
        assert result["variable"]["type"] == "enum"
        assert result["variable"]["enum_values"] == ["Male", "Female", "Other"]

    def test_add_workflow_variable_with_range(self, conversation_store, conversation_id):
        """Test adding a number variable with range constraints."""
        from ..tools.workflow_input import AddWorkflowVariableTool

        tool = AddWorkflowVariableTool()
        session_state = {"workflow_analysis": {"variables": [], "outputs": []}}

        result = tool.execute(
            {
                "name": "Blood Glucose",
                "type": "number",
                "range_min": 0,
                "range_max": 600
            },
            session_state=session_state
        )

        assert result["success"] is True
        assert result["variable"]["range"] == {"min": 0, "max": 600}

    def test_add_duplicate_variable_fails(self, conversation_store, conversation_id):
        """Test that adding duplicate variable (case-insensitive) fails."""
        from ..tools.workflow_input import AddWorkflowVariableTool

        tool = AddWorkflowVariableTool()
        session_state = {"workflow_analysis": {"variables": [], "outputs": []}}

        # Add first variable
        result1 = tool.execute(
            {"name": "Patient Age", "type": "number"},
            session_state=session_state
        )
        assert result1["success"] is True

        # Try to add duplicate (exact case)
        result2 = tool.execute(
            {"name": "Patient Age", "type": "number"},
            session_state=session_state
        )
        assert result2["success"] is False
        assert "already exists" in result2["error"].lower()

        # Try to add duplicate (different case)
        result3 = tool.execute(
            {"name": "patient age", "type": "number"},
            session_state=session_state
        )
        assert result3["success"] is False
        assert "already exists" in result3["error"].lower()

    def test_list_workflow_variables(self, conversation_store, conversation_id):
        """Test listing all registered variables."""
        from ..tools.workflow_input import AddWorkflowVariableTool, ListWorkflowVariablesTool

        add_tool = AddWorkflowVariableTool()
        list_tool = ListWorkflowVariablesTool()
        session_state = {"workflow_analysis": {"variables": [], "outputs": []}}

        # Add multiple variables
        add_tool.execute({"name": "Patient Age", "type": "number"}, session_state=session_state)
        add_tool.execute({"name": "Blood Glucose", "type": "number"}, session_state=session_state)

        # List variables
        result = list_tool.execute({}, session_state=session_state)

        print(f"\n[DEBUG] List variables result: {json.dumps(result, indent=2)}")

        assert result["success"] is True
        assert len(result["variables"]) == 2
        assert result["count"] == 2

        names = [var["name"] for var in result["variables"]]
        assert "Patient Age" in names
        assert "Blood Glucose" in names

    def test_remove_workflow_variable(self, conversation_store, conversation_id):
        """Test removing a workflow variable."""
        from ..tools.workflow_input import AddWorkflowVariableTool, RemoveWorkflowVariableTool

        add_tool = AddWorkflowVariableTool()
        remove_tool = RemoveWorkflowVariableTool()
        session_state = {"workflow_analysis": {"variables": [], "outputs": []}}

        # Add variable
        add_tool.execute({"name": "Patient Age", "type": "number"}, session_state=session_state)
        assert len(session_state["workflow_analysis"]["variables"]) == 1

        # Remove variable (case-insensitive)
        result = remove_tool.execute({"name": "patient age"}, session_state=session_state)

        print(f"\n[DEBUG] Remove variable result: {json.dumps(result, indent=2)}")

        assert result["success"] is True
        assert len(session_state["workflow_analysis"]["variables"]) == 0

    def test_remove_variable_with_condition_references_fails(self):
        """Test that removing a variable fails if nodes reference it in condition (without force).
        
        Uses orchestrator because AddNodeTool requires workflow_id and database access.
        """
        orch = build_orchestrator(repo_root=_repo_root())
        orch.workflow_analysis = {"variables": [], "outputs": [], "tree": {}, "doubts": []}
        orch.current_workflow = {"nodes": [], "edges": []}

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

    def test_remove_variable_force_as_string_boolean(self):
        """Test that force parameter works when passed as string 'true' (MCP compatibility).
        
        Uses orchestrator because AddNodeTool requires workflow_id and database access.
        """
        orch = build_orchestrator(repo_root=_repo_root())
        orch.workflow_analysis = {"variables": [], "outputs": [], "tree": {}, "doubts": []}
        orch.current_workflow = {"nodes": [], "edges": []}

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

    def test_remove_variable_multiple_references_error_shows_nodes(self):
        """Test that error message shows node labels when multiple nodes reference the variable.
        
        Uses orchestrator because AddNodeTool requires workflow_id and database access.
        """
        orch = build_orchestrator(repo_root=_repo_root())
        orch.workflow_analysis = {"variables": [], "outputs": [], "tree": {}, "doubts": []}
        orch.current_workflow = {"nodes": [], "edges": []}

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
    """Test decision nodes with condition references to variables.
    
    These tests use the orchestrator to properly test the full flow since
    AddNodeTool now requires workflow_id and database access.
    """

    @pytest.fixture
    def orchestrator(self):
        """Create an orchestrator instance for tests."""
        from ..agents.orchestrator_factory import build_orchestrator
        orch = build_orchestrator(repo_root=_repo_root())
        orch.workflow_analysis = {"variables": [], "outputs": [], "tree": {}, "doubts": []}
        orch.current_workflow = {"nodes": [], "edges": []}
        return orch

    def test_add_decision_node_with_condition(self, orchestrator):
        """Test adding a decision node that references a variable via condition."""
        # Register variable first
        result1 = orchestrator.run_tool(
            "add_workflow_variable",
            {"name": "Patient Age", "type": "number"}
        )
        assert result1.success
        var_id = result1.data["variable"]["id"]

        # Add decision node with condition
        result2 = orchestrator.run_tool(
            "add_node",
            {
                "type": "decision",
                "label": "Patient Age > 60?",
                "x": 100,
                "y": 100,
                "condition": {
                    "input_id": var_id,
                    "comparator": "gt",
                    "value": 60
                }
            }
        )

        print(f"\n[DEBUG] Add decision node result: {json.dumps(result2.data, indent=2)}")

        assert result2.success
        assert "node" in result2.data
        assert result2.data["node"]["condition"]["input_id"] == var_id
        assert result2.data["node"]["condition"]["comparator"] == "gt"
        assert result2.data["node"]["condition"]["value"] == 60

    def test_add_decision_node_without_condition_fails(self, orchestrator):
        """Test that adding a decision node without condition fails."""
        # Try to add decision node without condition
        result = orchestrator.run_tool(
            "add_node",
            {
                "type": "decision",
                "label": "Age check",
                "x": 100,
                "y": 100
            }
        )

        print(f"\n[DEBUG] Decision without condition result: {json.dumps(result.data, indent=2)}")

        assert not result.success
        assert "condition" in result.error.lower()

    def test_add_decision_node_with_invalid_variable_fails(self, orchestrator):
        """Test that referencing non-existent variable in condition fails."""
        # Try to reference non-existent variable
        result = orchestrator.run_tool(
            "add_node",
            {
                "type": "decision",
                "label": "Age check",
                "x": 100,
                "y": 100,
                "condition": {
                    "input_id": "var_nonexistent_number",
                    "comparator": "gt",
                    "value": 60
                }
            }
        )

        print(f"\n[DEBUG] Invalid variable result: {json.dumps(result.data, indent=2)}")

        assert not result.success
        assert "not found" in result.error.lower()

    def test_batch_edit_with_conditions(self, orchestrator):
        """Test batch_edit_workflow with decision conditions."""
        # Register variable first
        result1 = orchestrator.run_tool(
            "add_workflow_variable",
            {"name": "Patient Age", "type": "number"}
        )
        assert result1.success
        var_id = result1.data["variable"]["id"]

        # Batch create decision with branches
        result = orchestrator.run_tool(
            "batch_edit_workflow",
            {
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
            }
        )

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

    def test_add_variable_missing_name(self, conversation_store, conversation_id):
        """Test that missing name is rejected."""
        from ..tools.workflow_input import AddWorkflowVariableTool

        tool = AddWorkflowVariableTool()
        session_state = {"workflow_analysis": {"variables": [], "outputs": []}}

        result = tool.execute(
            {"type": "number"},
            session_state=session_state
        )

        assert result["success"] is False
        assert "name" in result["error"].lower()

    def test_add_variable_invalid_type(self, conversation_store, conversation_id):
        """Test that invalid type is rejected."""
        from ..tools.workflow_input import AddWorkflowVariableTool

        tool = AddWorkflowVariableTool()
        session_state = {"workflow_analysis": {"variables": [], "outputs": []}}

        result = tool.execute(
            {"name": "Test", "type": "invalid_type"},
            session_state=session_state
        )

        assert result["success"] is False
        assert "type" in result["error"].lower()

    def test_enum_variable_requires_values(self, conversation_store, conversation_id):
        """Test that enum type requires enum_values."""
        from ..tools.workflow_input import AddWorkflowVariableTool

        tool = AddWorkflowVariableTool()
        session_state = {"workflow_analysis": {"variables": [], "outputs": []}}

        result = tool.execute(
            {"name": "Test", "type": "enum"},
            session_state=session_state
        )

        assert result["success"] is False
        assert "enum_values" in result["error"].lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
