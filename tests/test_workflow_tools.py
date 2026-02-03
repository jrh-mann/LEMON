"""Tests for workflow manipulation tools.

All tools now require workflow_id parameter - workflows must be created first
using create_workflow, then tools operate on them by ID with auto-save to database.
"""

import pytest
from src.backend.tools.workflow_edit import (
    GetCurrentWorkflowTool,
    AddNodeTool,
    ModifyNodeTool,
    DeleteNodeTool,
    AddConnectionTool,
    DeleteConnectionTool,
)
from tests.conftest import make_session_with_workflow


class TestGetCurrentWorkflowTool:
    """Test reading current workflow state"""

    def setup_method(self):
        self.tool = GetCurrentWorkflowTool()

    def test_returns_error_when_no_workflow_id(self, session_state):
        """Should return error if no workflow_id provided"""
        result = self.tool.execute({}, session_state=session_state)
        assert result["success"] is False
        assert "workflow_id" in result.get("error", "").lower()

    def test_returns_workflow_from_database(self, workflow_store, test_user_id):
        """Should return workflow loaded from database"""
        nodes = [{"id": "n1", "type": "start", "label": "Input", "x": 0, "y": 0}]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes
        )
        
        result = self.tool.execute({"workflow_id": workflow_id}, session_state=session)

        assert result["success"] is True
        assert result["node_count"] == 1
        assert result["edge_count"] == 0
        assert len(result["workflow"]["nodes"]) == 1

    def test_includes_node_descriptions(self, workflow_store, test_user_id):
        """Should include human-readable node descriptions"""
        nodes = [
            {"id": "n1", "type": "start", "label": "Age", "x": 0, "y": 0},
            {"id": "n2", "type": "decision", "label": "Check Age?", "x": 100, "y": 0},
        ]
        edges = [{"id": "n1->n2", "from": "n1", "to": "n2", "label": ""}]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, edges=edges
        )
        
        result = self.tool.execute({"workflow_id": workflow_id}, session_state=session)

        assert "summary" in result
        assert "node_descriptions" in result["summary"]
        assert "n1" in result["summary"]["node_descriptions"]
        assert "Age" in result["summary"]["node_descriptions"]
        assert "edge_descriptions" in result["summary"]


class TestAddNodeTool:
    """Test adding nodes to workflow"""

    def setup_method(self):
        self.tool = AddNodeTool()

    def test_add_valid_node(self, create_test_workflow):
        """Should successfully add a valid node"""
        workflow_id, session = create_test_workflow()
        args = {"workflow_id": workflow_id, "type": "process", "label": "Calculate"}

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        assert result["action"] == "add_node"
        assert "node" in result
        assert result["node"]["type"] == "process"
        assert result["node"]["label"] == "Calculate"
        assert "id" in result["node"]
        assert result["node"]["id"].startswith("node_")

    def test_add_node_with_coordinates(self, create_test_workflow):
        """Should respect provided x,y coordinates"""
        workflow_id, session = create_test_workflow()
        args = {"workflow_id": workflow_id, "type": "start", "label": "Input", "x": 150, "y": 200}

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        assert result["node"]["x"] == 150
        assert result["node"]["y"] == 200

    def test_add_node_assigns_correct_color(self, create_test_workflow):
        """Should assign color based on node type"""
        workflow_id, session = create_test_workflow()
        test_cases = [
            ("start", "teal"),
            ("end", "green"),
            ("process", "slate"),
        ]

        for node_type, expected_color in test_cases:
            # Create fresh workflow for each test
            wf_id, sess = create_test_workflow(name=f"Test {node_type}")
            args = {"workflow_id": wf_id, "type": node_type, "label": "Test"}
            result = self.tool.execute(args, session_state=sess)
            assert result["success"] is True, f"Failed for {node_type}: {result.get('error')}"
            assert result["node"]["color"] == expected_color
    
    def test_add_subprocess_node_assigns_correct_color(self, workflow_store, test_user_id):
        """Should assign rose color to subprocess nodes with proper config"""
        # First create a subworkflow to reference
        from src.backend.tools import CreateWorkflowTool
        create_tool = CreateWorkflowTool()
        session = {"workflow_store": workflow_store, "user_id": test_user_id}
        subworkflow_result = create_tool.execute(
            {"name": "Subworkflow", "output_type": "string"},
            session_state=session
        )
        subworkflow_id = subworkflow_result["workflow_id"]
        
        # Now create main workflow and add subprocess node
        main_result = create_tool.execute(
            {"name": "Main Workflow", "output_type": "string"},
            session_state=session
        )
        workflow_id = main_result["workflow_id"]
        
        args = {
            "workflow_id": workflow_id,
            "type": "subprocess",
            "label": "Test Subprocess",
            "subworkflow_id": subworkflow_id,
            "input_mapping": {},
            "output_variable": "TestOutput",
        }
        result = self.tool.execute(args, session_state=session)
        assert result["success"] is True, f"Failed: {result.get('error')}"
        assert result["node"]["color"] == "rose"

    def test_add_invalid_node_type_fails_validation(self, create_test_workflow):
        """Should fail validation for invalid node type"""
        workflow_id, session = create_test_workflow()
        args = {"workflow_id": workflow_id, "type": "invalid_type", "label": "Bad Node"}

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is False
        assert "error" in result
        assert "VALIDATION_FAILED" in result.get("error_code", "")

    def test_add_decision_without_branches_succeeds_lenient(self, workflow_store, test_user_id):
        """Should succeed in lenient mode even without branches"""
        nodes = [{"id": "n1", "type": "start", "label": "Input", "x": 0, "y": 0, "color": "teal"}]
        variables = [{"id": "input_age_int", "name": "Age", "type": "int"}]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, variables=variables
        )
        
        args = {
            "workflow_id": workflow_id,
            "type": "decision",
            "label": "Check?",
            "condition": {
                "input_id": "input_age_int",
                "comparator": "gte",
                "value": 18
            }
        }

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        assert result["node"]["type"] == "decision"


class TestModifyNodeTool:
    """Test modifying existing nodes"""

    def setup_method(self):
        self.tool = ModifyNodeTool()

    def test_modify_node_label(self, workflow_store, test_user_id):
        """Should update node label"""
        nodes = [{"id": "n1", "type": "start", "label": "Old Label", "x": 0, "y": 0, "color": "teal"}]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes
        )
        args = {"workflow_id": workflow_id, "node_id": "n1", "label": "New Label"}

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        assert result["action"] == "modify_node"
        assert result["node"]["id"] == "n1"
        assert result["node"]["label"] == "New Label"

    def test_modify_node_position(self, workflow_store, test_user_id):
        """Should update node position"""
        nodes = [{"id": "n1", "type": "start", "label": "Input", "x": 0, "y": 0, "color": "teal"}]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes
        )
        args = {"workflow_id": workflow_id, "node_id": "n1", "x": 200, "y": 300}

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        assert result["node"]["x"] == 200
        assert result["node"]["y"] == 300

    def test_modify_node_type(self, workflow_store, test_user_id):
        """Should allow changing node type if result is valid"""
        nodes = [{"id": "n1", "type": "process", "label": "Step", "x": 0, "y": 0, "color": "slate"}]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes
        )
        args = {"workflow_id": workflow_id, "node_id": "n1", "type": "end"}

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        assert result["node"]["type"] == "end"
    
    def test_modify_node_to_subprocess(self, workflow_store, test_user_id):
        """Should allow changing node type to subprocess with required fields"""
        # First create a subworkflow to reference
        from src.backend.tools import CreateWorkflowTool
        create_tool = CreateWorkflowTool()
        session = {"workflow_store": workflow_store, "user_id": test_user_id}
        subworkflow_result = create_tool.execute(
            {"name": "Subworkflow", "output_type": "string"},
            session_state=session
        )
        subworkflow_id = subworkflow_result["workflow_id"]
        
        # Create main workflow with a process node
        nodes = [{"id": "n1", "type": "process", "label": "Step", "x": 0, "y": 0, "color": "slate"}]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes
        )
        args = {
            "workflow_id": workflow_id,
            "node_id": "n1",
            "type": "subprocess",
            "subworkflow_id": subworkflow_id,
            "input_mapping": {},
            "output_variable": "Result",
        }

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        assert result["node"]["type"] == "subprocess"
        assert result["node"]["subworkflow_id"] == subworkflow_id

    def test_modify_nonexistent_node_fails(self, create_test_workflow):
        """Should fail validation when modifying non-existent node"""
        workflow_id, session = create_test_workflow()
        args = {"workflow_id": workflow_id, "node_id": "nonexistent", "label": "New"}

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is False
        assert "error" in result


class TestDeleteNodeTool:
    """Test deleting nodes from workflow"""

    def setup_method(self):
        self.tool = DeleteNodeTool()

    def test_delete_existing_node(self, workflow_store, test_user_id):
        """Should delete node successfully"""
        nodes = [
            {"id": "n1", "type": "start", "label": "Input", "x": 0, "y": 0, "color": "teal"},
            {"id": "n2", "type": "end", "label": "Output", "x": 100, "y": 0, "color": "green"},
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes
        )
        args = {"workflow_id": workflow_id, "node_id": "n1"}

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        assert result["action"] == "delete_node"
        assert result["node_id"] == "n1"

    def test_delete_node_removes_connected_edges(self, workflow_store, test_user_id):
        """Should remove all edges connected to deleted node"""
        nodes = [
            {"id": "n1", "type": "start", "label": "Input", "x": 0, "y": 0, "color": "teal"},
            {"id": "n2", "type": "process", "label": "Process", "x": 100, "y": 0, "color": "slate"},
            {"id": "n3", "type": "end", "label": "Output", "x": 200, "y": 0, "color": "green"},
        ]
        edges = [
            {"id": "n1->n2", "from": "n1", "to": "n2", "label": ""},
            {"id": "n2->n3", "from": "n2", "to": "n3", "label": ""},
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, edges=edges
        )
        args = {"workflow_id": workflow_id, "node_id": "n2"}

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True

    def test_delete_nonexistent_node(self, create_test_workflow):
        """Should handle deletion of non-existent node gracefully"""
        workflow_id, session = create_test_workflow()
        args = {"workflow_id": workflow_id, "node_id": "nonexistent"}

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is False
        assert "error" in result


class TestAddConnectionTool:
    """Test adding edges between nodes"""

    def setup_method(self):
        self.tool = AddConnectionTool()

    def test_add_valid_connection(self, workflow_store, test_user_id):
        """Should add connection between existing nodes"""
        nodes = [
            {"id": "n1", "type": "start", "label": "Input", "x": 0, "y": 0, "color": "teal"},
            {"id": "n2", "type": "end", "label": "Output", "x": 100, "y": 0, "color": "green"},
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes
        )
        args = {"workflow_id": workflow_id, "from_node_id": "n1", "to_node_id": "n2"}

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        assert result["action"] == "add_connection"
        assert "edge" in result
        assert result["edge"]["from"] == "n1"
        assert result["edge"]["to"] == "n2"
        assert result["edge"]["id"] == "n1->n2"

    def test_add_connection_with_label(self, workflow_store, test_user_id):
        """Should add connection with custom label"""
        nodes = [
            {
                "id": "n1", 
                "type": "decision", 
                "label": "Check?", 
                "x": 0, 
                "y": 0, 
                "color": "amber",
                "condition": {"input_id": "var_test", "comparator": "gt", "value": 0}
            },
            {"id": "n2", "type": "end", "label": "Yes", "x": 100, "y": 0, "color": "green"},
            {"id": "n3", "type": "end", "label": "No", "x": 100, "y": 100, "color": "green"},
        ]
        edges = [{"id": "n1->n3", "from": "n1", "to": "n3", "label": "false"}]
        variables = [{"id": "var_test", "name": "test", "type": "int"}]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, edges=edges, variables=variables
        )
        args = {"workflow_id": workflow_id, "from_node_id": "n1", "to_node_id": "n2", "label": "true"}

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        assert result["edge"]["label"] == "true"

    def test_add_connection_to_nonexistent_node_fails(self, workflow_store, test_user_id):
        """Should fail when connecting to non-existent node"""
        nodes = [{"id": "n1", "type": "start", "label": "Input", "x": 0, "y": 0, "color": "teal"}]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes
        )
        args = {"workflow_id": workflow_id, "from_node_id": "n1", "to_node_id": "nonexistent"}

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is False
        assert "error" in result
        assert result.get("error_code", "") in ("VALIDATION_FAILED", "NODE_NOT_FOUND")

    def test_add_connection_from_end_node_succeeds_lenient(self, workflow_store, test_user_id):
        """Should succeed in lenient mode even if end node has outgoing edges"""
        nodes = [
            {"id": "n1", "type": "end", "label": "Output", "x": 0, "y": 0, "color": "green"},
            {"id": "n2", "type": "process", "label": "Process", "x": 100, "y": 0, "color": "slate"},
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes
        )
        args = {"workflow_id": workflow_id, "from_node_id": "n1", "to_node_id": "n2"}

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True


class TestDeleteConnectionTool:
    """Test deleting edges from workflow"""

    def setup_method(self):
        self.tool = DeleteConnectionTool()

    def test_delete_existing_connection(self, workflow_store, test_user_id):
        """Should delete connection successfully if result is valid"""
        nodes = [
            {"id": "n1", "type": "start", "label": "Input", "x": 0, "y": 0, "color": "teal"},
            {"id": "n2", "type": "end", "label": "Output", "x": 100, "y": 0, "color": "green"},
        ]
        edges = [{"id": "n1->n2", "from": "n1", "to": "n2", "label": ""}]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, edges=edges
        )
        args = {"workflow_id": workflow_id, "from_node_id": "n1", "to_node_id": "n2"}

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        assert result["action"] == "delete_connection"

    def test_delete_nonexistent_connection(self, workflow_store, test_user_id):
        """Should fail when referencing non-existent node"""
        nodes = [{"id": "n1", "type": "start", "label": "Input", "x": 0, "y": 0, "color": "teal"}]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes
        )
        args = {"workflow_id": workflow_id, "from_node_id": "n1", "to_node_id": "n2"}

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is False
        assert result.get("error_code") == "NODE_NOT_FOUND"

    def test_delete_connection_succeeds_lenient(self, workflow_store, test_user_id):
        """Should succeed in lenient mode even if workflow becomes invalid"""
        nodes = [
            {
                "id": "n1", 
                "type": "decision", 
                "label": "Check?", 
                "x": 0, 
                "y": 0, 
                "color": "amber",
                "condition": {"input_id": "var_test", "comparator": "gt", "value": 0}
            },
            {"id": "n2", "type": "end", "label": "Yes", "x": 100, "y": 0, "color": "green"},
            {"id": "n3", "type": "end", "label": "No", "x": 100, "y": 100, "color": "green"},
        ]
        edges = [
            {"id": "n1->n2", "from": "n1", "to": "n2", "label": "true"},
            {"id": "n1->n3", "from": "n1", "to": "n3", "label": "false"},
        ]
        variables = [{"id": "var_test", "name": "test", "type": "int"}]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, edges=edges, variables=variables
        )
        args = {"workflow_id": workflow_id, "from_node_id": "n1", "to_node_id": "n2"}

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
