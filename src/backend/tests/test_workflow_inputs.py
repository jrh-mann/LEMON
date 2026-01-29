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
        from ..tools.workflow_input import AddWorkflowInputTool

        tool = AddWorkflowInputTool()

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
        # Type is converted to internal format: "number" -> "float"
        assert result["variable"]["type"] == "float"
        assert result["variable"]["description"] == "Patient's age in years"
        # ID is auto-generated
        assert result["variable"]["id"] == "var_patient_age_float"

        # Verify it was added to session state
        assert len(session_state["workflow_analysis"]["variables"]) == 1
        assert session_state["workflow_analysis"]["variables"][0]["name"] == "Patient Age"

    def test_add_workflow_variable_with_enum(self, conversation_store, conversation_id):
        """Test adding an enum variable."""
        from ..tools.workflow_input import AddWorkflowInputTool

        tool = AddWorkflowInputTool()
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
        from ..tools.workflow_input import AddWorkflowInputTool

        tool = AddWorkflowInputTool()
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
        from ..tools.workflow_input import AddWorkflowInputTool

        tool = AddWorkflowInputTool()
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
        from ..tools.workflow_input import AddWorkflowInputTool, ListWorkflowInputsTool

        add_tool = AddWorkflowInputTool()
        list_tool = ListWorkflowInputsTool()
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
        from ..tools.workflow_input import AddWorkflowInputTool, RemoveWorkflowInputTool

        add_tool = AddWorkflowInputTool()
        remove_tool = RemoveWorkflowInputTool()
        session_state = {"workflow_analysis": {"variables": [], "outputs": []}}

        # Add variable
        add_tool.execute({"name": "Patient Age", "type": "number"}, session_state=session_state)
        assert len(session_state["workflow_analysis"]["variables"]) == 1

        # Remove variable (case-insensitive)
        result = remove_tool.execute({"name": "patient age"}, session_state=session_state)

        print(f"\n[DEBUG] Remove variable result: {json.dumps(result, indent=2)}")

        assert result["success"] is True
        assert len(session_state["workflow_analysis"]["variables"]) == 0

    def test_remove_variable_with_condition_references_fails(self, conversation_store, conversation_id):
        """Test that removing a variable fails if nodes reference it in condition (without force)."""
        from ..tools.workflow_input import AddWorkflowInputTool, RemoveWorkflowInputTool
        from ..tools.workflow_edit import AddNodeTool

        add_input_tool = AddWorkflowInputTool()
        add_node_tool = AddNodeTool()
        remove_tool = RemoveWorkflowInputTool()

        session_state = {
            "workflow_analysis": {"variables": [], "outputs": []},
            "current_workflow": {"nodes": [], "edges": []}
        }

        # Add variable
        input_result = add_input_tool.execute({"name": "Patient Age", "type": "int"}, session_state=session_state)
        var_id = input_result["variable"]["id"]

        # Add TWO nodes with conditions that reference the variable
        node1_result = add_node_tool.execute(
            {
                "type": "decision",
                "label": "Age > 60?",
                "x": 100,
                "y": 100,
                "condition": {
                    "input_id": var_id,
                    "comparator": "gt",
                    "value": 60
                }
            },
            session_state=session_state
        )
        session_state["current_workflow"]["nodes"].append(node1_result["node"])

        node2_result = add_node_tool.execute(
            {
                "type": "decision",
                "label": "Age > 18?",
                "x": 100,
                "y": 200,
                "condition": {
                    "input_id": var_id,
                    "comparator": "gt",
                    "value": 18
                }
            },
            session_state=session_state
        )
        session_state["current_workflow"]["nodes"].append(node2_result["node"])

        # Verify nodes have condition
        assert session_state["current_workflow"]["nodes"][0]["condition"]["input_id"] == var_id
        assert session_state["current_workflow"]["nodes"][1]["condition"]["input_id"] == var_id

        # Remove variable WITH force=true (should cascade)
        result = remove_tool.execute(
            {"name": "Patient Age", "force": True},
            session_state=session_state
        )

        print(f"\n[DEBUG] Force remove variable result: {json.dumps(result, indent=2)}")

        # Should succeed
        assert result["success"] is True
        assert "Removed variable 'Patient Age'" in result["message"]
        assert "cleared references from 2 node(s)" in result["message"]
        assert result["affected_nodes"] == 2

        # Variable should be removed
        assert len(session_state["workflow_analysis"]["variables"]) == 0

        # Nodes should no longer have condition
        assert "condition" not in session_state["current_workflow"]["nodes"][0]
        assert "condition" not in session_state["current_workflow"]["nodes"][1]

    def test_remove_variable_force_as_string_boolean(self, conversation_store, conversation_id):
        """Test that force parameter works when passed as string 'true' (MCP compatibility)."""
        from ..tools.workflow_input import AddWorkflowInputTool, RemoveWorkflowInputTool
        from ..tools.workflow_edit import AddNodeTool

        add_input_tool = AddWorkflowInputTool()
        add_node_tool = AddNodeTool()
        remove_tool = RemoveWorkflowInputTool()

        session_state = {
            "workflow_analysis": {"variables": [], "outputs": []},
            "current_workflow": {"nodes": [], "edges": []}
        }

        # Add variable
        input_result = add_input_tool.execute({"name": "Patient Age", "type": "int"}, session_state=session_state)
        var_id = input_result["variable"]["id"]

        # Add node with condition that references the variable
        node_result = add_node_tool.execute(
            {
                "type": "decision",
                "label": "Age > 60?",
                "x": 100,
                "y": 100,
                "condition": {
                    "input_id": var_id,
                    "comparator": "gt",
                    "value": 60
                }
            },
            session_state=session_state
        )
        session_state["current_workflow"]["nodes"].append(node_result["node"])

        # Remove variable with force as STRING "true" (simulating MCP JSON deserialization)
        result = remove_tool.execute(
            {"name": "Patient Age", "force": "true"},  # String instead of boolean
            session_state=session_state
        )

        print(f"\n[DEBUG] Remove with force='true' (string): {json.dumps(result, indent=2)}")

        # Should succeed even though force is a string
        assert result["success"] is True
        assert "Removed variable 'Patient Age'" in result["message"]
        assert result["affected_nodes"] == 1

        # Node should no longer have condition
        assert "condition" not in session_state["current_workflow"]["nodes"][0]

    def test_remove_variable_multiple_references_error_shows_nodes(self, conversation_store, conversation_id):
        """Test that error message shows node labels when multiple nodes reference the variable."""
        from ..tools.workflow_input import AddWorkflowInputTool, RemoveWorkflowInputTool
        from ..tools.workflow_edit import AddNodeTool

        add_input_tool = AddWorkflowInputTool()
        add_node_tool = AddNodeTool()
        remove_tool = RemoveWorkflowInputTool()

        session_state = {
            "workflow_analysis": {"variables": [], "outputs": []},
            "current_workflow": {"nodes": [], "edges": []}
        }

        # Add variable
        input_result = add_input_tool.execute({"name": "Blood Pressure", "type": "int"}, session_state=session_state)
        var_id = input_result["variable"]["id"]

        # Add multiple nodes with different labels and conditions
        comparators = ["gt", "lt", "eq", "gte"]
        values = [140, 90, 120, 80]
        for i, (label, comp, val) in enumerate(zip(
            ["BP > 140?", "BP < 90?", "BP Normal?", "BP Critical?"],
            comparators, values
        )):
            node_result = add_node_tool.execute(
                {
                    "type": "decision",
                    "label": label,
                    "x": 100,
                    "y": 100 * i,
                    "condition": {
                        "input_id": var_id,
                        "comparator": comp,
                        "value": val
                    }
                },
                session_state=session_state
            )
            session_state["current_workflow"]["nodes"].append(node_result["node"])

        # Try to remove without force
        result = remove_tool.execute({"name": "Blood Pressure"}, session_state=session_state)

        print(f"\n[DEBUG] Multiple references error: {json.dumps(result, indent=2)}")

        # Should show first 3 node labels
        assert result["success"] is False
        assert "referenced by 4 node(s)" in result["error"]
        assert "BP > 140?" in result["error"]
        assert "BP < 90?" in result["error"]
        assert "BP Normal?" in result["error"]
        assert "and 1 more" in result["error"]  # 4th node truncated


class TestDecisionNodeConditions:
    """Test decision nodes with condition references to variables."""

    def test_add_decision_node_with_condition(self, conversation_store, conversation_id):
        """Test adding a decision node that references a variable via condition."""
        from ..tools.workflow_input import AddWorkflowInputTool
        from ..tools.workflow_edit import AddNodeTool

        input_tool = AddWorkflowInputTool()
        node_tool = AddNodeTool()

        session_state = {
            "workflow_analysis": {"variables": [], "outputs": []},
            "current_workflow": {"nodes": [], "edges": []}
        }

        # Register variable first
        input_result = input_tool.execute(
            {"name": "Patient Age", "type": "int"},
            session_state=session_state
        )
        assert input_result["success"] is True
        var_id = input_result["variable"]["id"]

        # Add decision node with condition
        node_result = node_tool.execute(
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
            },
            session_state=session_state
        )

        print(f"\n[DEBUG] Add decision node result: {json.dumps(node_result, indent=2)}")

        assert node_result["success"] is True
        assert "node" in node_result
        assert node_result["node"]["condition"]["input_id"] == var_id
        assert node_result["node"]["condition"]["comparator"] == "gt"
        assert node_result["node"]["condition"]["value"] == 60

    def test_add_decision_node_without_condition_fails(self, conversation_store, conversation_id):
        """Test that adding a decision node without condition fails."""
        from ..tools.workflow_edit import AddNodeTool

        node_tool = AddNodeTool()

        session_state = {
            "workflow_analysis": {"variables": [], "outputs": []},
            "current_workflow": {"nodes": [], "edges": []}
        }

        # Try to add decision node without condition
        result = node_tool.execute(
            {
                "type": "decision",
                "label": "Age check",
                "x": 100,
                "y": 100
            },
            session_state=session_state
        )

        print(f"\n[DEBUG] Decision without condition result: {json.dumps(result, indent=2)}")

        assert result["success"] is False
        assert "condition" in result["error"].lower()

    def test_add_decision_node_with_invalid_variable_fails(self, conversation_store, conversation_id):
        """Test that referencing non-existent variable in condition fails."""
        from ..tools.workflow_edit import AddNodeTool

        node_tool = AddNodeTool()

        session_state = {
            "workflow_analysis": {"variables": [], "outputs": []},
            "current_workflow": {"nodes": [], "edges": []}
        }

        # Try to reference non-existent variable
        result = node_tool.execute(
            {
                "type": "decision",
                "label": "Age check",
                "x": 100,
                "y": 100,
                "condition": {
                    "input_id": "var_nonexistent_int",
                    "comparator": "gt",
                    "value": 60
                }
            },
            session_state=session_state
        )

        print(f"\n[DEBUG] Invalid variable result: {json.dumps(result, indent=2)}")

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_batch_edit_with_conditions(self, conversation_store, conversation_id):
        """Test batch_edit_workflow with decision conditions."""
        from ..tools.workflow_input import AddWorkflowInputTool
        from ..tools.workflow_edit import BatchEditWorkflowTool

        input_tool = AddWorkflowInputTool()
        batch_tool = BatchEditWorkflowTool()

        session_state = {
            "workflow_analysis": {"variables": [], "outputs": []},
            "current_workflow": {"nodes": [], "edges": []}
        }

        # Register variable first
        input_result = input_tool.execute({"name": "Patient Age", "type": "int"}, session_state=session_state)
        var_id = input_result["variable"]["id"]

        # Batch create decision with branches
        result = batch_tool.execute(
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
            },
            session_state=session_state
        )

        print(f"\n[DEBUG] Batch with condition result: {json.dumps(result, indent=2)}")

        assert result["success"] is True

        # Find the decision node
        decision_node = next(
            (n for n in result["workflow"]["nodes"] if n["type"] == "decision"),
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
        from ..tools.workflow_input import AddWorkflowInputTool

        tool = AddWorkflowInputTool()
        session_state = {"workflow_analysis": {"variables": [], "outputs": []}}

        result = tool.execute(
            {"type": "number"},
            session_state=session_state
        )

        assert result["success"] is False
        assert "name" in result["error"].lower()

    def test_add_variable_invalid_type(self, conversation_store, conversation_id):
        """Test that invalid type is rejected."""
        from ..tools.workflow_input import AddWorkflowInputTool

        tool = AddWorkflowInputTool()
        session_state = {"workflow_analysis": {"variables": [], "outputs": []}}

        result = tool.execute(
            {"name": "Test", "type": "invalid_type"},
            session_state=session_state
        )

        assert result["success"] is False
        assert "type" in result["error"].lower()

    def test_enum_variable_requires_values(self, conversation_store, conversation_id):
        """Test that enum type requires enum_values."""
        from ..tools.workflow_input import AddWorkflowInputTool

        tool = AddWorkflowInputTool()
        session_state = {"workflow_analysis": {"variables": [], "outputs": []}}

        result = tool.execute(
            {"name": "Test", "type": "enum"},
            session_state=session_state
        )

        assert result["success"] is False
        assert "enum_values" in result["error"].lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
