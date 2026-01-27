"""Test workflow input management and node-input linking.

Tests the complete flow:
1. Register inputs with add_workflow_input
2. Create nodes that reference inputs
3. Validate input references
4. List and remove inputs
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


class TestWorkflowInputManagement:
    """Test input registration and management."""

    def test_add_workflow_input_basic(self, conversation_store, conversation_id):
        """Test adding a simple workflow input."""
        from ..tools.workflow_input import AddWorkflowInputTool

        tool = AddWorkflowInputTool()

        # Start with empty workflow_analysis
        session_state = {"workflow_analysis": {"inputs": [], "outputs": []}}

        result = tool.execute(
            {
                "name": "Patient Age",
                "type": "number",
                "description": "Patient's age in years"
            },
            session_state=session_state
        )

        print(f"\n[DEBUG] Add input result: {json.dumps(result, indent=2)}")

        assert result["success"] is True, f"Failed to add input: {result.get('error')}"
        assert "input" in result
        assert result["input"]["name"] == "Patient Age"
        # Type is converted to internal format: "number" -> "float"
        assert result["input"]["type"] == "float"
        assert result["input"]["description"] == "Patient's age in years"
        # ID is auto-generated
        assert result["input"]["id"] == "input_patient_age_float"

        # Verify it was added to session state
        assert len(session_state["workflow_analysis"]["inputs"]) == 1
        assert session_state["workflow_analysis"]["inputs"][0]["name"] == "Patient Age"

    def test_add_workflow_input_with_enum(self, conversation_store, conversation_id):
        """Test adding an enum input."""
        from ..tools.workflow_input import AddWorkflowInputTool

        tool = AddWorkflowInputTool()
        session_state = {"workflow_analysis": {"inputs": [], "outputs": []}}

        result = tool.execute(
            {
                "name": "Patient Gender",
                "type": "enum",
                "enum_values": ["Male", "Female", "Other"]
            },
            session_state=session_state
        )

        assert result["success"] is True
        assert result["input"]["type"] == "enum"
        assert result["input"]["enum_values"] == ["Male", "Female", "Other"]

    def test_add_workflow_input_with_range(self, conversation_store, conversation_id):
        """Test adding a number input with range constraints."""
        from ..tools.workflow_input import AddWorkflowInputTool

        tool = AddWorkflowInputTool()
        session_state = {"workflow_analysis": {"inputs": [], "outputs": []}}

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
        assert result["input"]["range"] == {"min": 0, "max": 600}

    def test_add_duplicate_input_fails(self, conversation_store, conversation_id):
        """Test that adding duplicate input (case-insensitive) fails."""
        from ..tools.workflow_input import AddWorkflowInputTool

        tool = AddWorkflowInputTool()
        session_state = {"workflow_analysis": {"inputs": [], "outputs": []}}

        # Add first input
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

    def test_list_workflow_inputs(self, conversation_store, conversation_id):
        """Test listing all registered inputs."""
        from ..tools.workflow_input import AddWorkflowInputTool, ListWorkflowInputsTool

        add_tool = AddWorkflowInputTool()
        list_tool = ListWorkflowInputsTool()
        session_state = {"workflow_analysis": {"inputs": [], "outputs": []}}

        # Add multiple inputs
        add_tool.execute({"name": "Patient Age", "type": "number"}, session_state=session_state)
        add_tool.execute({"name": "Blood Glucose", "type": "number"}, session_state=session_state)

        # List inputs
        result = list_tool.execute({}, session_state=session_state)

        print(f"\n[DEBUG] List inputs result: {json.dumps(result, indent=2)}")

        assert result["success"] is True
        assert len(result["inputs"]) == 2
        assert result["count"] == 2

        names = [inp["name"] for inp in result["inputs"]]
        assert "Patient Age" in names
        assert "Blood Glucose" in names

    def test_remove_workflow_input(self, conversation_store, conversation_id):
        """Test removing a workflow input."""
        from ..tools.workflow_input import AddWorkflowInputTool, RemoveWorkflowInputTool

        add_tool = AddWorkflowInputTool()
        remove_tool = RemoveWorkflowInputTool()
        session_state = {"workflow_analysis": {"inputs": [], "outputs": []}}

        # Add input
        add_tool.execute({"name": "Patient Age", "type": "number"}, session_state=session_state)
        assert len(session_state["workflow_analysis"]["inputs"]) == 1

        # Remove input (case-insensitive)
        result = remove_tool.execute({"name": "patient age"}, session_state=session_state)

        print(f"\n[DEBUG] Remove input result: {json.dumps(result, indent=2)}")

        assert result["success"] is True
        assert len(session_state["workflow_analysis"]["inputs"]) == 0

    def test_remove_input_with_node_references_fails(self, conversation_store, conversation_id):
        """Test that removing an input fails if nodes reference it (without force)."""
        from ..tools.workflow_input import AddWorkflowInputTool, RemoveWorkflowInputTool
        from ..tools.workflow_edit import AddNodeTool

        add_input_tool = AddWorkflowInputTool()
        add_node_tool = AddNodeTool()
        remove_tool = RemoveWorkflowInputTool()

        session_state = {
            "workflow_analysis": {"inputs": [], "outputs": []},
            "current_workflow": {"nodes": [], "edges": []}
        }

        # Add input
        input_result = add_input_tool.execute({"name": "Patient Age", "type": "number"}, session_state=session_state)
        input_id = input_result["input"]["id"]  # Get the auto-generated ID

        # Add TWO nodes that reference the input (decision nodes require condition)
        node1_result = add_node_tool.execute(
            {
                "type": "decision",
                "label": "Age > 60?",
                "input_ref": "Patient Age",
                "x": 100,
                "y": 100,
                "condition": {
                    "input_id": input_id,
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
                "input_ref": "Patient Age",
                "x": 100,
                "y": 200,
                "condition": {
                    "input_id": input_id,
                    "comparator": "gt",
                    "value": 18
                }
            },
            session_state=session_state
        )
        session_state["current_workflow"]["nodes"].append(node2_result["node"])

        # Verify nodes have input_ref
        assert session_state["current_workflow"]["nodes"][0].get("input_ref") == "Patient Age"
        assert session_state["current_workflow"]["nodes"][1].get("input_ref") == "Patient Age"

        # Remove input WITH force=true (should cascade)
        result = remove_tool.execute(
            {"name": "Patient Age", "force": True},
            session_state=session_state
        )

        print(f"\n[DEBUG] Force remove input result: {json.dumps(result, indent=2)}")

        # Should succeed
        assert result["success"] is True
        assert "Removed input 'Patient Age'" in result["message"]
        assert "cleared references from 2 node(s)" in result["message"]
        assert result["affected_nodes"] == 2

        # Input should be removed
        assert len(session_state["workflow_analysis"]["inputs"]) == 0

        # Nodes should no longer have input_ref
        assert "input_ref" not in session_state["current_workflow"]["nodes"][0]
        assert "input_ref" not in session_state["current_workflow"]["nodes"][1]

    def test_remove_input_force_as_string_boolean(self, conversation_store, conversation_id):
        """Test that force parameter works when passed as string 'true' (MCP compatibility)."""
        from ..tools.workflow_input import AddWorkflowInputTool, RemoveWorkflowInputTool
        from ..tools.workflow_edit import AddNodeTool

        add_input_tool = AddWorkflowInputTool()
        add_node_tool = AddNodeTool()
        remove_tool = RemoveWorkflowInputTool()

        session_state = {
            "workflow_analysis": {"inputs": [], "outputs": []},
            "current_workflow": {"nodes": [], "edges": []}
        }

        # Add input
        input_result = add_input_tool.execute({"name": "Patient Age", "type": "number"}, session_state=session_state)
        input_id = input_result["input"]["id"]  # Get the auto-generated ID

        # Add node that references the input (decision nodes require condition)
        node_result = add_node_tool.execute(
            {
                "type": "decision",
                "label": "Age > 60?",
                "input_ref": "Patient Age",
                "x": 100,
                "y": 100,
                "condition": {
                    "input_id": input_id,
                    "comparator": "gt",
                    "value": 60
                }
            },
            session_state=session_state
        )
        session_state["current_workflow"]["nodes"].append(node_result["node"])

        # Remove input with force as STRING "true" (simulating MCP JSON deserialization)
        result = remove_tool.execute(
            {"name": "Patient Age", "force": "true"},  # String instead of boolean
            session_state=session_state
        )

        print(f"\n[DEBUG] Remove with force='true' (string): {json.dumps(result, indent=2)}")

        # Should succeed even though force is a string
        assert result["success"] is True
        assert "Removed input 'Patient Age'" in result["message"]
        assert result["affected_nodes"] == 1

        # Node should no longer have input_ref
        assert "input_ref" not in session_state["current_workflow"]["nodes"][0]

    def test_remove_input_multiple_references_error_shows_nodes(self, conversation_store, conversation_id):
        """Test that error message shows node labels when multiple nodes reference the input."""
        from ..tools.workflow_input import AddWorkflowInputTool, RemoveWorkflowInputTool
        from ..tools.workflow_edit import AddNodeTool

        add_input_tool = AddWorkflowInputTool()
        add_node_tool = AddNodeTool()
        remove_tool = RemoveWorkflowInputTool()

        session_state = {
            "workflow_analysis": {"inputs": [], "outputs": []},
            "current_workflow": {"nodes": [], "edges": []}
        }

        # Add input
        input_result = add_input_tool.execute({"name": "Blood Pressure", "type": "number"}, session_state=session_state)
        input_id = input_result["input"]["id"]

        # Add multiple nodes with different labels and conditions
        comparators = ["gt", "lt", "eq", "gte"]  # Different comparators for each node
        values = [140, 90, 120, 80]
        for i, (label, comp, val) in enumerate(zip(
            ["BP > 140?", "BP < 90?", "BP Normal?", "BP Critical?"],
            comparators, values
        )):
            node_result = add_node_tool.execute(
                {
                    "type": "decision",
                    "label": label,
                    "input_ref": "Blood Pressure",
                    "x": 100,
                    "y": 100 * i,
                    "condition": {
                        "input_id": input_id,
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


class TestNodeInputLinking:
    """Test linking nodes to inputs via input_ref."""

    def test_add_node_with_input_ref(self, conversation_store, conversation_id):
        """Test adding a node that references an input."""
        from ..tools.workflow_input import AddWorkflowInputTool
        from ..tools.workflow_edit import AddNodeTool

        input_tool = AddWorkflowInputTool()
        node_tool = AddNodeTool()

        session_state = {
            "workflow_analysis": {"inputs": [], "outputs": []},
            "current_workflow": {"nodes": [], "edges": []}
        }

        # Register input first
        input_result = input_tool.execute(
            {"name": "Patient Age", "type": "number"},
            session_state=session_state
        )
        assert input_result["success"] is True
        input_id = input_result["input"]["id"]

        # Add node that references the input (decision nodes require condition)
        node_result = node_tool.execute(
            {
                "type": "decision",
                "label": "Patient Age > 60?",
                "input_ref": "Patient Age",  # Name-based reference
                "x": 100,
                "y": 100,
                "condition": {
                    "input_id": input_id,
                    "comparator": "gt",
                    "value": 60
                }
            },
            session_state=session_state
        )

        print(f"\n[DEBUG] Add node with input_ref result: {json.dumps(node_result, indent=2)}")

        assert node_result["success"] is True
        assert "node" in node_result
        assert node_result["node"]["input_ref"] == "Patient Age"

    def test_add_node_with_invalid_input_ref_fails(self, conversation_store, conversation_id):
        """Test that referencing non-existent input fails."""
        from ..tools.workflow_edit import AddNodeTool

        node_tool = AddNodeTool()

        session_state = {
            "workflow_analysis": {"inputs": [], "outputs": []},
            "current_workflow": {"nodes": [], "edges": []}
        }

        # Try to reference non-existent input
        result = node_tool.execute(
            {
                "type": "decision",
                "label": "Age check",
                "input_ref": "Nonexistent Input",
                "x": 100,
                "y": 100
            },
            session_state=session_state
        )

        print(f"\n[DEBUG] Invalid input_ref result: {json.dumps(result, indent=2)}")

        assert result["success"] is False
        assert "not found" in result["error"].lower() or "does not exist" in result["error"].lower()

    def test_add_node_with_input_ref_case_insensitive(self, conversation_store, conversation_id):
        """Test that input_ref matching is case-insensitive."""
        from ..tools.workflow_input import AddWorkflowInputTool
        from ..tools.workflow_edit import AddNodeTool

        input_tool = AddWorkflowInputTool()
        node_tool = AddNodeTool()

        session_state = {
            "workflow_analysis": {"inputs": [], "outputs": []},
            "current_workflow": {"nodes": [], "edges": []}
        }

        # Register input with mixed case
        input_result = input_tool.execute(
            {"name": "Patient Age", "type": "number"},
            session_state=session_state
        )
        input_id = input_result["input"]["id"]

        # Reference with different case (decision nodes require condition)
        result = node_tool.execute(
            {
                "type": "decision",
                "label": "Age check",
                "input_ref": "patient age",  # lowercase
                "x": 100,
                "y": 100,
                "condition": {
                    "input_id": input_id,
                    "comparator": "gt",
                    "value": 0
                }
            },
            session_state=session_state
        )

        assert result["success"] is True
        # Stores the original case from the reference
        assert result["node"]["input_ref"] == "patient age"

    def test_modify_node_input_ref(self, conversation_store, conversation_id):
        """Test updating a node's input_ref."""
        from ..tools.workflow_input import AddWorkflowInputTool
        from ..tools.workflow_edit import AddNodeTool, ModifyNodeTool

        input_tool = AddWorkflowInputTool()
        add_node_tool = AddNodeTool()
        modify_node_tool = ModifyNodeTool()

        session_state = {
            "workflow_analysis": {"inputs": [], "outputs": []},
            "current_workflow": {"nodes": [], "edges": []}
        }

        # Register two inputs
        age_input = input_tool.execute({"name": "Patient Age", "type": "number"}, session_state=session_state)
        glucose_input = input_tool.execute({"name": "Blood Glucose", "type": "number"}, session_state=session_state)
        age_id = age_input["input"]["id"]
        glucose_id = glucose_input["input"]["id"]

        # Add node referencing first input (decision nodes require condition)
        add_result = add_node_tool.execute(
            {
                "type": "decision",
                "label": "Age check",
                "input_ref": "Patient Age",
                "x": 100,
                "y": 100,
                "condition": {
                    "input_id": age_id,
                    "comparator": "gt",
                    "value": 0
                }
            },
            session_state=session_state
        )
        node_id = add_result["node"]["id"]

        # Update orchestrator state (simulate what respond() does)
        session_state["current_workflow"]["nodes"].append(add_result["node"])

        # Modify to reference second input (update condition too)
        modify_result = modify_node_tool.execute(
            {
                "node_id": node_id,
                "input_ref": "Blood Glucose",
                "label": "Glucose check",
                "condition": {
                    "input_id": glucose_id,
                    "comparator": "gt",
                    "value": 100
                }
            },
            session_state=session_state
        )

        print(f"\n[DEBUG] Modify input_ref result: {json.dumps(modify_result, indent=2)}")

        assert modify_result["success"] is True
        assert modify_result["node"]["input_ref"] == "Blood Glucose"
        assert modify_result["node"]["label"] == "Glucose check"

    def test_batch_edit_with_input_refs(self, conversation_store, conversation_id):
        """Test batch_edit_workflow with input_refs."""
        from ..tools.workflow_input import AddWorkflowInputTool
        from ..tools.workflow_edit import BatchEditWorkflowTool

        input_tool = AddWorkflowInputTool()
        batch_tool = BatchEditWorkflowTool()

        session_state = {
            "workflow_analysis": {"inputs": [], "outputs": []},
            "current_workflow": {"nodes": [], "edges": []}
        }

        # Register inputs first
        input_result = input_tool.execute({"name": "Patient Age", "type": "number"}, session_state=session_state)
        input_id = input_result["input"]["id"]

        # Batch create decision with branches, referencing input (requires condition)
        result = batch_tool.execute(
            {
                "operations": [
                    {
                        "op": "add_node",
                        "id": "temp_decision",
                        "type": "decision",
                        "label": "Patient Age > 60?",
                        "input_ref": "Patient Age",  # Reference the input
                        "x": 100,
                        "y": 100,
                        "condition": {
                            "input_id": input_id,
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

        print(f"\n[DEBUG] Batch with input_ref result: {json.dumps(result, indent=2)}")

        assert result["success"] is True

        # Find the decision node
        decision_node = next(
            (n for n in result["workflow"]["nodes"] if n["type"] == "decision"),
            None
        )
        assert decision_node is not None
        assert decision_node["input_ref"] == "Patient Age"


class TestInputValidation:
    """Test input validation and error handling."""

    def test_add_input_missing_name(self, conversation_store, conversation_id):
        """Test that missing name is rejected."""
        from ..tools.workflow_input import AddWorkflowInputTool

        tool = AddWorkflowInputTool()
        session_state = {"workflow_analysis": {"inputs": [], "outputs": []}}

        result = tool.execute(
            {"type": "number"},
            session_state=session_state
        )

        assert result["success"] is False
        assert "name" in result["error"].lower()

    def test_add_input_invalid_type(self, conversation_store, conversation_id):
        """Test that invalid type is rejected."""
        from ..tools.workflow_input import AddWorkflowInputTool

        tool = AddWorkflowInputTool()
        session_state = {"workflow_analysis": {"inputs": [], "outputs": []}}

        result = tool.execute(
            {"name": "Test", "type": "invalid_type"},
            session_state=session_state
        )

        assert result["success"] is False
        assert "type" in result["error"].lower()

    def test_enum_input_requires_values(self, conversation_store, conversation_id):
        """Test that enum type requires enum_values."""
        from ..tools.workflow_input import AddWorkflowInputTool

        tool = AddWorkflowInputTool()
        session_state = {"workflow_analysis": {"inputs": [], "outputs": []}}

        result = tool.execute(
            {"name": "Test", "type": "enum"},
            session_state=session_state
        )

        assert result["success"] is False
        assert "enum_values" in result["error"].lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
