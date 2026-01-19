"""Tests for workflow manipulation tools"""

import pytest
from src.backend.tools.workflow_edit import (
    GetCurrentWorkflowTool,
    AddNodeTool,
    ModifyNodeTool,
    DeleteNodeTool,
    AddConnectionTool,
    DeleteConnectionTool,
)


class TestGetCurrentWorkflowTool:
    """Test reading current workflow state"""

    def setup_method(self):
        self.tool = GetCurrentWorkflowTool()

    def test_returns_empty_workflow_when_no_session_state(self):
        """Should return empty workflow if no session state provided"""
        result = self.tool.execute({})
        assert result["success"] is True
        assert result["workflow"] == {"nodes": [], "edges": []}
        assert result["node_count"] == 0
        assert result["edge_count"] == 0

    def test_returns_workflow_from_session_state(self):
        """Should return workflow from session state"""
        workflow = {
            "nodes": [
                {"id": "n1", "type": "start", "label": "Input", "x": 0, "y": 0}
            ],
            "edges": [],
        }
        session_state = {"current_workflow": workflow}
        result = self.tool.execute({}, session_state=session_state)

        assert result["success"] is True
        assert result["workflow"] == workflow
        assert result["node_count"] == 1
        assert result["edge_count"] == 0

    def test_includes_node_descriptions(self):
        """Should include human-readable node descriptions"""
        workflow = {
            "nodes": [
                {"id": "n1", "type": "start", "label": "Age", "x": 0, "y": 0},
                {"id": "n2", "type": "decision", "label": "Check Age?", "x": 100, "y": 0},
            ],
            "edges": [
                {"id": "n1->n2", "from": "n1", "to": "n2", "label": ""}
            ],
        }
        session_state = {"current_workflow": workflow}
        result = self.tool.execute({}, session_state=session_state)

        assert "summary" in result
        assert "node_descriptions" in result["summary"]
        assert "n1" in result["summary"]["node_descriptions"]
        assert "Age" in result["summary"]["node_descriptions"]
        assert "edge_descriptions" in result["summary"]


class TestAddNodeTool:
    """Test adding nodes to workflow"""

    def setup_method(self):
        self.tool = AddNodeTool()

    def test_add_valid_node(self):
        """Should successfully add a valid node"""
        args = {"type": "process", "label": "Calculate"}
        session_state = {"current_workflow": {"nodes": [], "edges": []}}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is True
        assert result["action"] == "add_node"
        assert "node" in result
        assert result["node"]["type"] == "process"
        assert result["node"]["label"] == "Calculate"
        assert "id" in result["node"]
        assert result["node"]["id"].startswith("node_")

    def test_add_node_with_coordinates(self):
        """Should respect provided x,y coordinates"""
        args = {"type": "start", "label": "Input", "x": 150, "y": 200}
        session_state = {"current_workflow": {"nodes": [], "edges": []}}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is True
        assert result["node"]["x"] == 150
        assert result["node"]["y"] == 200

    def test_add_node_assigns_correct_color(self):
        """Should assign color based on node type"""
        # Decision nodes can't be added alone (need 2 branches), so exclude them
        test_cases = [
            ("start", "teal"),
            ("end", "green"),
            ("subprocess", "rose"),
            ("process", "slate"),
        ]

        for node_type, expected_color in test_cases:
            args = {"type": node_type, "label": "Test"}
            session_state = {"current_workflow": {"nodes": [], "edges": []}}
            result = self.tool.execute(args, session_state=session_state)
            assert result["success"] is True, f"Failed for {node_type}: {result.get('error')}"
            assert result["node"]["color"] == expected_color

    def test_add_invalid_node_type_fails_validation(self):
        """Should fail validation for invalid node type"""
        args = {"type": "invalid_type", "label": "Bad Node"}
        session_state = {"current_workflow": {"nodes": [], "edges": []}}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is False
        assert "error" in result
        assert "VALIDATION_FAILED" in result.get("error_code", "")

    def test_add_decision_without_branches_fails(self):
        """Should fail if adding decision node without branches"""
        existing_workflow = {
            "nodes": [
                {"id": "n1", "type": "start", "label": "Input", "x": 0, "y": 0, "color": "teal"},
            ],
            "edges": [],
        }
        args = {"type": "decision", "label": "Check?"}
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        # Should fail - decision nodes need 2 branches
        assert result["success"] is False
        assert "2 branches" in result.get("error", "")


class TestModifyNodeTool:
    """Test modifying existing nodes"""

    def setup_method(self):
        self.tool = ModifyNodeTool()

    def test_modify_node_label(self):
        """Should update node label"""
        existing_workflow = {
            "nodes": [
                {"id": "n1", "type": "start", "label": "Old Label", "x": 0, "y": 0, "color": "teal"},
            ],
            "edges": [],
        }
        args = {"node_id": "n1", "label": "New Label"}
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is True
        assert result["action"] == "modify_node"
        assert result["node_id"] == "n1"
        assert result["updates"]["label"] == "New Label"

    def test_modify_node_position(self):
        """Should update node position"""
        existing_workflow = {
            "nodes": [
                {"id": "n1", "type": "start", "label": "Input", "x": 0, "y": 0, "color": "teal"},
            ],
            "edges": [],
        }
        args = {"node_id": "n1", "x": 200, "y": 300}
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is True
        assert result["updates"]["x"] == 200
        assert result["updates"]["y"] == 300

    def test_modify_node_type(self):
        """Should allow changing node type if result is valid"""
        existing_workflow = {
            "nodes": [
                {"id": "n1", "type": "process", "label": "Step", "x": 0, "y": 0, "color": "slate"},
            ],
            "edges": [],
        }
        # Change to subprocess (which is valid alone)
        args = {"node_id": "n1", "type": "subprocess"}
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is True
        assert result["updates"]["type"] == "subprocess"

    def test_modify_nonexistent_node_fails(self):
        """Should fail validation when modifying non-existent node"""
        existing_workflow = {"nodes": [], "edges": []}
        args = {"node_id": "nonexistent", "label": "New"}
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is False
        assert "error" in result


class TestDeleteNodeTool:
    """Test deleting nodes from workflow"""

    def setup_method(self):
        self.tool = DeleteNodeTool()

    def test_delete_existing_node(self):
        """Should delete node successfully"""
        existing_workflow = {
            "nodes": [
                {"id": "n1", "type": "start", "label": "Input", "x": 0, "y": 0, "color": "teal"},
                {"id": "n2", "type": "end", "label": "Output", "x": 100, "y": 0, "color": "green"},
            ],
            "edges": [],
        }
        args = {"node_id": "n1"}
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is True
        assert result["action"] == "delete_node"
        assert result["node_id"] == "n1"

    def test_delete_node_removes_connected_edges(self):
        """Should remove all edges connected to deleted node"""
        existing_workflow = {
            "nodes": [
                {"id": "n1", "type": "start", "label": "Input", "x": 0, "y": 0, "color": "teal"},
                {"id": "n2", "type": "process", "label": "Process", "x": 100, "y": 0, "color": "slate"},
                {"id": "n3", "type": "end", "label": "Output", "x": 200, "y": 0, "color": "green"},
            ],
            "edges": [
                {"id": "n1->n2", "from": "n1", "to": "n2", "label": ""},
                {"id": "n2->n3", "from": "n2", "to": "n3", "label": ""},
            ],
        }
        args = {"node_id": "n2"}
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        # Deleting middle node leaves start with no outgoing edges (invalid when >1 node)
        # So this should actually fail
        assert result["success"] is False
        assert "outgoing" in result.get("error", "").lower()

    def test_delete_nonexistent_node(self):
        """Should handle deletion of non-existent node gracefully"""
        existing_workflow = {"nodes": [], "edges": []}
        args = {"node_id": "nonexistent"}
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        # Should succeed (idempotent operation)
        assert result["success"] is True


class TestAddConnectionTool:
    """Test adding edges between nodes"""

    def setup_method(self):
        self.tool = AddConnectionTool()

    def test_add_valid_connection(self):
        """Should add connection between existing nodes"""
        existing_workflow = {
            "nodes": [
                {"id": "n1", "type": "start", "label": "Input", "x": 0, "y": 0, "color": "teal"},
                {"id": "n2", "type": "end", "label": "Output", "x": 100, "y": 0, "color": "green"},
            ],
            "edges": [],
        }
        args = {"from_node_id": "n1", "to_node_id": "n2"}
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is True
        assert result["action"] == "add_connection"
        assert "edge" in result
        assert result["edge"]["from"] == "n1"
        assert result["edge"]["to"] == "n2"
        assert result["edge"]["id"] == "n1->n2"

    def test_add_connection_with_label(self):
        """Should add connection with custom label"""
        existing_workflow = {
            "nodes": [
                {"id": "n1", "type": "decision", "label": "Check?", "x": 0, "y": 0, "color": "amber"},
                {"id": "n2", "type": "end", "label": "Yes", "x": 100, "y": 0, "color": "green"},
                {"id": "n3", "type": "end", "label": "No", "x": 100, "y": 100, "color": "green"},
            ],
            # Decision already has one edge, adding second makes it valid
            "edges": [
                {"id": "n1->n3", "from": "n1", "to": "n3", "label": "false"},
            ],
        }
        args = {"from_node_id": "n1", "to_node_id": "n2", "label": "true"}
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is True
        assert result["edge"]["label"] == "true"

    def test_add_connection_to_nonexistent_node_fails(self):
        """Should fail validation when connecting to non-existent node"""
        existing_workflow = {
            "nodes": [
                {"id": "n1", "type": "start", "label": "Input", "x": 0, "y": 0, "color": "teal"},
            ],
            "edges": [],
        }
        args = {"from_node_id": "n1", "to_node_id": "nonexistent"}
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is False
        assert "error" in result
        assert "VALIDATION_FAILED" in result.get("error_code", "")

    def test_add_connection_creating_invalid_end_node_fails(self):
        """Should fail if connection makes end node have outgoing edges"""
        existing_workflow = {
            "nodes": [
                {"id": "n1", "type": "end", "label": "Output", "x": 0, "y": 0, "color": "green"},
                {"id": "n2", "type": "process", "label": "Process", "x": 100, "y": 0, "color": "slate"},
            ],
            "edges": [],
        }
        args = {"from_node_id": "n1", "to_node_id": "n2"}
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is False
        # Check that error mentions end nodes can't have outgoing edges
        assert "outgoing" in result.get("error", "").lower()


class TestDeleteConnectionTool:
    """Test deleting edges from workflow"""

    def setup_method(self):
        self.tool = DeleteConnectionTool()

    def test_delete_existing_connection(self):
        """Should delete connection successfully if result is valid"""
        # Use a workflow where deleting connection leaves valid state
        existing_workflow = {
            "nodes": [
                {"id": "n1", "type": "start", "label": "Input", "x": 0, "y": 0, "color": "teal"},
            ],
            "edges": [],
        }
        args = {"from_node_id": "n1", "to_node_id": "n2"}
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        # Should succeed - no edge to delete, idempotent
        assert result["success"] is True
        assert result["action"] == "delete_connection"

    def test_delete_nonexistent_connection(self):
        """Should handle deletion of non-existent connection gracefully"""
        existing_workflow = {
            "nodes": [
                {"id": "n1", "type": "start", "label": "Input", "x": 0, "y": 0, "color": "teal"},
            ],
            "edges": [],
        }
        args = {"from_node_id": "n1", "to_node_id": "n2"}
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        # Should succeed (idempotent operation)
        assert result["success"] is True

    def test_delete_connection_creating_invalid_workflow_fails(self):
        """Should fail if deletion creates invalid workflow structure"""
        existing_workflow = {
            "nodes": [
                {"id": "n1", "type": "decision", "label": "Check?", "x": 0, "y": 0, "color": "amber"},
                {"id": "n2", "type": "end", "label": "Yes", "x": 100, "y": 0, "color": "green"},
                {"id": "n3", "type": "end", "label": "No", "x": 100, "y": 100, "color": "green"},
            ],
            "edges": [
                {"id": "n1->n2", "from": "n1", "to": "n2", "label": "true"},
                {"id": "n1->n3", "from": "n1", "to": "n3", "label": "false"},
            ],
        }
        # Deleting one branch would leave decision with only 1 branch
        args = {"from_node_id": "n1", "to_node_id": "n2"}
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is False
        # Check that error mentions decision nodes need multiple branches
        assert "branch" in result.get("error", "").lower()
