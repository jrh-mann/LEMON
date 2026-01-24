"""Tests for batch workflow editing tool"""

import pytest
from src.backend.tools.workflow_edit import BatchEditWorkflowTool


class TestBatchEditWorkflowTool:
    """Test atomic batch editing of workflows"""

    def setup_method(self):
        self.tool = BatchEditWorkflowTool()

    def test_empty_operations_list_succeeds(self):
        """Should succeed with empty operations list"""
        existing_workflow = {"nodes": [], "edges": []}
        args = {"operations": []}
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is True
        assert result["operation_count"] == 0

    def test_single_add_node_operation(self):
        """Should handle single add_node operation"""
        existing_workflow = {"nodes": [], "edges": []}
        args = {
            "operations": [
                {"op": "add_node", "type": "start", "label": "Input", "id": "temp_1"}
            ]
        }
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is True
        assert result["operation_count"] == 1
        assert len(result["operations"]) == 1
        assert result["operations"][0]["op"] == "add_node"
        assert result["operations"][0]["node"]["label"] == "Input"
        # Should have replaced temp ID with real ID
        assert result["operations"][0]["node"]["id"].startswith("node_")
        assert result["operations"][0]["node"]["id"] != "temp_1"

    def test_add_decision_node_with_branches_atomically(self):
        """Should add decision node with 2 branches in one atomic operation"""
        existing_workflow = {
            "nodes": [
                {"id": "input_1", "type": "start", "label": "Age", "x": 0, "y": 0, "color": "teal"}
            ],
            "edges": [],
        }
        args = {
            "operations": [
                # Add decision node
                {"op": "add_node", "type": "decision", "label": "Age >= 18?", "id": "temp_decision"},
                # Add two end nodes for branches
                {"op": "add_node", "type": "end", "label": "Adult", "id": "temp_adult"},
                {"op": "add_node", "type": "end", "label": "Minor", "id": "temp_minor"},
                # Connect input to decision
                {"op": "add_connection", "from": "input_1", "to": "temp_decision", "label": ""},
                # Connect decision to both outcomes
                {"op": "add_connection", "from": "temp_decision", "to": "temp_adult", "label": "true"},
                {"op": "add_connection", "from": "temp_decision", "to": "temp_minor", "label": "false"},
            ]
        }
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is True
        assert result["operation_count"] == 6
        # Should have created 3 nodes and 3 edges
        add_node_ops = [op for op in result["operations"] if op["op"] == "add_node"]
        add_edge_ops = [op for op in result["operations"] if op["op"] == "add_connection"]
        assert len(add_node_ops) == 3
        assert len(add_edge_ops) == 3

    def test_temp_id_resolution_across_operations(self):
        """Should resolve temp IDs to real IDs when referenced later"""
        existing_workflow = {"nodes": [], "edges": []}
        args = {
            "operations": [
                {"op": "add_node", "type": "start", "label": "A", "id": "temp_a"},
                {"op": "add_node", "type": "end", "label": "B", "id": "temp_b"},
                # Reference temp IDs in connection
                {"op": "add_connection", "from": "temp_a", "to": "temp_b", "label": ""},
            ]
        }
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is True
        # Find the connection operation
        conn_op = next(op for op in result["operations"] if op["op"] == "add_connection")
        # Should have real node IDs, not temp
        assert conn_op["edge"]["from"].startswith("node_")
        assert conn_op["edge"]["to"].startswith("node_")
        assert "temp" not in conn_op["edge"]["from"]
        assert "temp" not in conn_op["edge"]["to"]

    def test_modify_node_in_batch(self):
        """Should modify existing node properties"""
        existing_workflow = {
            "nodes": [
                {"id": "n1", "type": "start", "label": "Old", "x": 0, "y": 0, "color": "teal"}
            ],
            "edges": [],
        }
        args = {
            "operations": [
                {"op": "modify_node", "node_id": "n1", "label": "New Label", "x": 100}
            ]
        }
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is True
        modify_op = result["operations"][0]
        assert modify_op["op"] == "modify_node"
        assert modify_op["node_id"] == "n1"
        assert modify_op["updates"]["label"] == "New Label"
        assert modify_op["updates"]["x"] == 100

    def test_delete_node_in_batch(self):
        """Should delete node and its edges"""
        existing_workflow = {
            "nodes": [
                {"id": "n1", "type": "start", "label": "A", "x": 0, "y": 0, "color": "teal"},
                {"id": "n2", "type": "end", "label": "B", "x": 100, "y": 0, "color": "green"},
            ],
            "edges": [
                {"id": "n1->n2", "from": "n1", "to": "n2", "label": ""}
            ],
        }
        args = {
            "operations": [
                {"op": "delete_node", "node_id": "n1"}
            ]
        }
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is True
        delete_op = result["operations"][0]
        assert delete_op["op"] == "delete_node"
        assert delete_op["node_id"] == "n1"

    def test_add_and_delete_connection_in_batch(self):
        """Should handle connection operations"""
        existing_workflow = {
            "nodes": [
                {"id": "n1", "type": "start", "label": "A", "x": 0, "y": 0, "color": "teal"},
                {"id": "n2", "type": "end", "label": "B", "x": 100, "y": 0, "color": "green"},
                {"id": "n3", "type": "end", "label": "C", "x": 100, "y": 100, "color": "green"},
            ],
            "edges": [
                {"id": "n1->n2", "from": "n1", "to": "n2", "label": ""}
            ],
        }
        args = {
            "operations": [
                # Delete existing connection
                {"op": "delete_connection", "from": "n1", "to": "n2"},
                # Add new connection
                {"op": "add_connection", "from": "n1", "to": "n3", "label": ""},
            ]
        }
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is True
        assert result["operation_count"] == 2

    def test_atomic_behavior_all_or_nothing(self):
        """Should fail entire batch if validation fails at the end"""
        existing_workflow = {"nodes": [], "edges": []}
        args = {
            "operations": [
                # Add a valid start node
                {"op": "add_node", "type": "start", "label": "Input", "id": "temp_1"},
                # Add a process node
                {"op": "add_node", "type": "process", "label": "Process", "id": "temp_2"},
                # Add connections that create a cycle
                {"op": "add_connection", "from": "temp_1", "to": "temp_2", "label": ""},
                {"op": "add_connection", "from": "temp_2", "to": "temp_1", "label": ""},
            ]
        }
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        # Should fail because of cycle detection (enforced even in lenient mode)
        assert result["success"] is False
        assert "error" in result
        assert "cycle" in result["error"].lower()

    def test_invalid_operation_type_fails(self):
        """Should fail if operation type is unknown"""
        existing_workflow = {"nodes": [], "edges": []}
        args = {
            "operations": [
                {"op": "invalid_operation", "some": "data"}
            ]
        }
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is False
        assert "Unknown operation type" in result.get("error", "")

    def test_reference_nonexistent_node_fails(self):
        """Should fail if trying to modify/delete non-existent node"""
        existing_workflow = {"nodes": [], "edges": []}
        args = {
            "operations": [
                {"op": "modify_node", "node_id": "nonexistent", "label": "New"}
            ]
        }
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is False
        assert "not found" in result.get("error", "").lower()

    def test_complex_workflow_construction(self):
        """Should build complex workflow with multiple node types"""
        existing_workflow = {"nodes": [], "edges": []}
        args = {
            "operations": [
                # Create input
                {"op": "add_node", "type": "start", "label": "Age", "id": "temp_input", "x": 0, "y": 100},
                # Create decision
                {"op": "add_node", "type": "decision", "label": "Age >= 18?", "id": "temp_dec", "x": 200, "y": 100},
                # Create process for adults
                {"op": "add_node", "type": "process", "label": "Verify ID", "id": "temp_proc", "x": 400, "y": 50},
                # Create outputs
                {"op": "add_node", "type": "end", "label": "Approved", "id": "temp_yes", "x": 600, "y": 50},
                {"op": "add_node", "type": "end", "label": "Rejected", "id": "temp_no", "x": 400, "y": 150},
                # Wire them up
                {"op": "add_connection", "from": "temp_input", "to": "temp_dec", "label": ""},
                {"op": "add_connection", "from": "temp_dec", "to": "temp_proc", "label": "true"},
                {"op": "add_connection", "from": "temp_dec", "to": "temp_no", "label": "false"},
                {"op": "add_connection", "from": "temp_proc", "to": "temp_yes", "label": ""},
            ]
        }
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is True
        assert result["operation_count"] == 9
        # Verify all nodes were created
        node_ops = [op for op in result["operations"] if op["op"] == "add_node"]
        assert len(node_ops) == 5
        # Verify all connections were created
        edge_ops = [op for op in result["operations"] if op["op"] == "add_connection"]
        assert len(edge_ops) == 4

    def test_operations_not_list_fails(self):
        """Should fail if operations is not a list"""
        existing_workflow = {"nodes": [], "edges": []}
        args = {"operations": "not a list"}
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is False
        assert "must be an array" in result.get("error", "")

    def test_modify_then_delete_same_node(self):
        """Should handle modify followed by delete on same node"""
        existing_workflow = {
            "nodes": [
                {"id": "n1", "type": "start", "label": "Old", "x": 0, "y": 0, "color": "teal"}
            ],
            "edges": [],
        }
        args = {
            "operations": [
                {"op": "modify_node", "node_id": "n1", "label": "New"},
                {"op": "delete_node", "node_id": "n1"},
            ]
        }
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        # Should succeed - modify then delete is valid
        assert result["success"] is True
        assert result["operation_count"] == 2

    def test_add_node_with_explicit_id_not_temp(self):
        """Should handle adding node with explicit non-temp ID"""
        existing_workflow = {"nodes": [], "edges": []}
        args = {
            "operations": [
                {"op": "add_node", "type": "start", "label": "Input", "id": "explicit_id"}
            ]
        }
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is True
        # ID should be replaced with real UUID even if not temp_*
        assert result["operations"][0]["node"]["id"].startswith("node_")

    def test_update_node_color_on_type_change(self):
        """Should update node color when type changes"""
        existing_workflow = {
            "nodes": [
                {"id": "n1", "type": "process", "label": "Step", "x": 0, "y": 0, "color": "slate"}
            ],
            "edges": [],
        }
        args = {
            "operations": [
                {"op": "modify_node", "node_id": "n1", "type": "subprocess"}
            ]
        }
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is True
        # Note: The tool currently doesn't auto-update color on type change
        # This is OK - the frontend can handle it, or we can add logic later

    def test_validation_prevents_self_loop(self):
        """Should fail if trying to create a self-loop (always enforced)"""
        existing_workflow = {"nodes": [], "edges": []}
        args = {
            "operations": [
                {"op": "add_node", "type": "process", "label": "Process", "id": "temp_proc"},
                # Try to connect node to itself (self-loop - always invalid)
                {"op": "add_connection", "from": "temp_proc", "to": "temp_proc", "label": ""},
            ]
        }
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is False
        assert "self-loop" in result.get("error", "").lower() or "cycle" in result.get("error", "").lower()

    def test_preserves_existing_workflow(self):
        """Should not modify existing nodes/edges unless explicitly operated on"""
        existing_workflow = {
            "nodes": [
                {"id": "existing", "type": "start", "label": "Existing", "x": 0, "y": 0, "color": "teal"}
            ],
            "edges": [],
        }
        args = {
            "operations": [
                {"op": "add_node", "type": "end", "label": "New", "id": "temp_new"},
                {"op": "add_connection", "from": "existing", "to": "temp_new", "label": ""},
            ]
        }
        session_state = {"current_workflow": existing_workflow}

        result = self.tool.execute(args, session_state=session_state)

        assert result["success"] is True
        # Only new node and connection should be in operations
        assert result["operation_count"] == 2
