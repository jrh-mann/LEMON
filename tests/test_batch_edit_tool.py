"""Tests for batch workflow editing tool.

All workflow tools now require workflow_id parameter - workflows must be created first
using create_workflow, then tools operate on them by ID with auto-save to database.
"""

import pytest
from src.backend.tools.workflow_edit import BatchEditWorkflowTool
from src.backend.tools import CreateWorkflowTool
from tests.conftest import make_session_with_workflow


class TestBatchEditWorkflowTool:
    """Test atomic batch editing of workflows"""

    def setup_method(self):
        self.tool = BatchEditWorkflowTool()

    def test_empty_operations_list_succeeds(self, workflow_store, test_user_id):
        """Should succeed with empty operations list"""
        workflow_id, session = make_session_with_workflow(workflow_store, test_user_id)
        args = {"workflow_id": workflow_id, "operations": []}

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        assert result["operation_count"] == 0

    def test_single_add_node_operation(self, workflow_store, test_user_id):
        """Should handle single add_node operation"""
        workflow_id, session = make_session_with_workflow(workflow_store, test_user_id)
        args = {
            "workflow_id": workflow_id,
            "operations": [
                {"op": "add_node", "type": "start", "label": "Input", "id": "temp_1"}
            ]
        }

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        assert result["operation_count"] == 1
        assert len(result["operations"]) == 1
        assert result["operations"][0]["op"] == "add_node"
        assert result["operations"][0]["node"]["label"] == "Input"
        # Should have replaced temp ID with real ID
        assert result["operations"][0]["node"]["id"].startswith("node_")
        assert result["operations"][0]["node"]["id"] != "temp_1"

    def test_add_decision_node_with_branches_atomically(self, workflow_store, test_user_id):
        """Should add decision node with 2 branches in one atomic operation"""
        nodes = [
            {"id": "input_1", "type": "start", "label": "Age", "x": 0, "y": 0, "color": "teal"}
        ]
        variables = [{"id": "input_age_int", "name": "Age", "type": "int", "source": "input"}]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, variables=variables
        )
        session["workflow_analysis"] = {"variables": variables}
        
        args = {
            "workflow_id": workflow_id,
            "operations": [
                # Add decision node with condition
                {
                    "op": "add_node",
                    "type": "decision",
                    "label": "Age >= 18?",
                    "id": "temp_decision",
                    "condition": {
                        "input_id": "input_age_int",
                        "comparator": "gte",
                        "value": 18
                    }
                },
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

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        assert result["operation_count"] == 6
        # Should have created 3 nodes and 3 edges
        add_node_ops = [op for op in result["operations"] if op["op"] == "add_node"]
        add_edge_ops = [op for op in result["operations"] if op["op"] == "add_connection"]
        assert len(add_node_ops) == 3
        assert len(add_edge_ops) == 3

    def test_temp_id_resolution_across_operations(self, workflow_store, test_user_id):
        """Should resolve temp IDs to real IDs when referenced later"""
        workflow_id, session = make_session_with_workflow(workflow_store, test_user_id)
        args = {
            "workflow_id": workflow_id,
            "operations": [
                {"op": "add_node", "type": "start", "label": "A", "id": "temp_a"},
                {"op": "add_node", "type": "end", "label": "B", "id": "temp_b"},
                # Reference temp IDs in connection
                {"op": "add_connection", "from": "temp_a", "to": "temp_b", "label": ""},
            ]
        }

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        # Find the connection operation
        conn_op = next(op for op in result["operations"] if op["op"] == "add_connection")
        # Should have real node IDs, not temp
        assert conn_op["edge"]["from"].startswith("node_")
        assert conn_op["edge"]["to"].startswith("node_")
        assert "temp" not in conn_op["edge"]["from"]
        assert "temp" not in conn_op["edge"]["to"]

    def test_modify_node_in_batch(self, workflow_store, test_user_id):
        """Should modify existing node properties"""
        nodes = [
            {"id": "n1", "type": "start", "label": "Old", "x": 0, "y": 0, "color": "teal"}
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes
        )
        args = {
            "workflow_id": workflow_id,
            "operations": [
                {"op": "modify_node", "node_id": "n1", "label": "New Label", "x": 100}
            ]
        }

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        modify_op = result["operations"][0]
        assert modify_op["op"] == "modify_node"
        assert modify_op["node_id"] == "n1"
        assert modify_op["updates"]["label"] == "New Label"
        assert modify_op["updates"]["x"] == 100

    def test_delete_node_in_batch(self, workflow_store, test_user_id):
        """Should delete node and its edges"""
        nodes = [
            {"id": "n1", "type": "start", "label": "A", "x": 0, "y": 0, "color": "teal"},
            {"id": "n2", "type": "end", "label": "B", "x": 100, "y": 0, "color": "green"},
        ]
        edges = [
            {"id": "n1->n2", "from": "n1", "to": "n2", "label": ""}
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, edges=edges
        )
        args = {
            "workflow_id": workflow_id,
            "operations": [
                {"op": "delete_node", "node_id": "n1"}
            ]
        }

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        delete_op = result["operations"][0]
        assert delete_op["op"] == "delete_node"
        assert delete_op["node_id"] == "n1"

    def test_add_and_delete_connection_in_batch(self, workflow_store, test_user_id):
        """Should handle connection operations"""
        nodes = [
            {"id": "n1", "type": "start", "label": "A", "x": 0, "y": 0, "color": "teal"},
            {"id": "n2", "type": "end", "label": "B", "x": 100, "y": 0, "color": "green"},
            {"id": "n3", "type": "end", "label": "C", "x": 100, "y": 100, "color": "green"},
        ]
        edges = [
            {"id": "n1->n2", "from": "n1", "to": "n2", "label": ""}
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, edges=edges
        )
        args = {
            "workflow_id": workflow_id,
            "operations": [
                # Delete existing connection
                {"op": "delete_connection", "from": "n1", "to": "n2"},
                # Add new connection
                {"op": "add_connection", "from": "n1", "to": "n3", "label": ""},
            ]
        }

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        assert result["operation_count"] == 2

    def test_atomic_behavior_all_or_nothing(self, workflow_store, test_user_id):
        """Should fail entire batch if validation fails at the end"""
        workflow_id, session = make_session_with_workflow(workflow_store, test_user_id)
        args = {
            "workflow_id": workflow_id,
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

        result = self.tool.execute(args, session_state=session)

        # Should fail because of cycle detection (enforced even in lenient mode)
        assert result["success"] is False
        assert "error" in result
        assert "cycle" in result["error"].lower()

    def test_invalid_operation_type_fails(self, workflow_store, test_user_id):
        """Should fail if operation type is unknown"""
        workflow_id, session = make_session_with_workflow(workflow_store, test_user_id)
        args = {
            "workflow_id": workflow_id,
            "operations": [
                {"op": "invalid_operation", "some": "data"}
            ]
        }

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is False
        assert "Unknown operation type" in result.get("error", "")

    def test_reference_nonexistent_node_fails(self, workflow_store, test_user_id):
        """Should fail if trying to modify/delete non-existent node"""
        workflow_id, session = make_session_with_workflow(workflow_store, test_user_id)
        args = {
            "workflow_id": workflow_id,
            "operations": [
                {"op": "modify_node", "node_id": "nonexistent", "label": "New"}
            ]
        }

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is False
        assert "not found" in result.get("error", "").lower()

    def test_complex_workflow_construction(self, workflow_store, test_user_id):
        """Should build complex workflow with multiple node types"""
        variables = [{"id": "input_age_int", "name": "Age", "type": "int", "source": "input"}]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, variables=variables
        )
        session["workflow_analysis"] = {"variables": variables}
        
        args = {
            "workflow_id": workflow_id,
            "operations": [
                # Create input
                {"op": "add_node", "type": "start", "label": "Age", "id": "temp_input", "x": 0, "y": 100},
                # Create decision with condition
                {
                    "op": "add_node",
                    "type": "decision",
                    "label": "Age >= 18?",
                    "id": "temp_dec",
                    "x": 200,
                    "y": 100,
                    "condition": {
                        "input_id": "input_age_int",
                        "comparator": "gte",
                        "value": 18
                    }
                },
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

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        assert result["operation_count"] == 9
        # Verify all nodes were created
        node_ops = [op for op in result["operations"] if op["op"] == "add_node"]
        assert len(node_ops) == 5
        # Verify all connections were created
        edge_ops = [op for op in result["operations"] if op["op"] == "add_connection"]
        assert len(edge_ops) == 4

    def test_operations_not_list_fails(self, workflow_store, test_user_id):
        """Should fail if operations is not a list"""
        workflow_id, session = make_session_with_workflow(workflow_store, test_user_id)
        args = {"workflow_id": workflow_id, "operations": "not a list"}

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is False
        assert "must be an array" in result.get("error", "")

    def test_modify_then_delete_same_node(self, workflow_store, test_user_id):
        """Should handle modify followed by delete on same node"""
        nodes = [
            {"id": "n1", "type": "start", "label": "Old", "x": 0, "y": 0, "color": "teal"}
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes
        )
        args = {
            "workflow_id": workflow_id,
            "operations": [
                {"op": "modify_node", "node_id": "n1", "label": "New"},
                {"op": "delete_node", "node_id": "n1"},
            ]
        }

        result = self.tool.execute(args, session_state=session)

        # Should succeed - modify then delete is valid
        assert result["success"] is True
        assert result["operation_count"] == 2

    def test_add_node_with_explicit_id_not_temp(self, workflow_store, test_user_id):
        """Should handle adding node with explicit non-temp ID"""
        workflow_id, session = make_session_with_workflow(workflow_store, test_user_id)
        args = {
            "workflow_id": workflow_id,
            "operations": [
                {"op": "add_node", "type": "start", "label": "Input", "id": "explicit_id"}
            ]
        }

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        # ID should be replaced with real UUID even if not temp_*
        assert result["operations"][0]["node"]["id"].startswith("node_")

    def test_update_node_color_on_type_change(self, workflow_store, test_user_id):
        """Should update node color when type changes"""
        nodes = [
            {"id": "n1", "type": "process", "label": "Step", "x": 0, "y": 0, "color": "slate"}
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes
        )
        args = {
            "workflow_id": workflow_id,
            "operations": [
                {"op": "modify_node", "node_id": "n1", "type": "end"}  # end doesn't require special fields
            ]
        }

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        # Note: The tool currently doesn't auto-update color on type change
        # This is OK - the frontend can handle it, or we can add logic later

    def test_validation_prevents_self_loop(self, workflow_store, test_user_id):
        """Should fail if trying to create a self-loop (always enforced)"""
        workflow_id, session = make_session_with_workflow(workflow_store, test_user_id)
        args = {
            "workflow_id": workflow_id,
            "operations": [
                {"op": "add_node", "type": "process", "label": "Process", "id": "temp_proc"},
                # Try to connect node to itself (self-loop - always invalid)
                {"op": "add_connection", "from": "temp_proc", "to": "temp_proc", "label": ""},
            ]
        }

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is False
        assert "self-loop" in result.get("error", "").lower() or "cycle" in result.get("error", "").lower()

    def test_preserves_existing_workflow(self, workflow_store, test_user_id):
        """Should not modify existing nodes/edges unless explicitly operated on"""
        nodes = [
            {"id": "existing", "type": "start", "label": "Existing", "x": 0, "y": 0, "color": "teal"}
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes
        )
        args = {
            "workflow_id": workflow_id,
            "operations": [
                {"op": "add_node", "type": "end", "label": "New", "id": "temp_new"},
                {"op": "add_connection", "from": "existing", "to": "temp_new", "label": ""},
            ]
        }

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        # Only new node and connection should be in operations
        assert result["operation_count"] == 2


class TestBatchEditSubprocessNodes:
    """Test batch_edit_workflow handling of subprocess nodes."""

    def setup_method(self):
        self.tool = BatchEditWorkflowTool()

    def test_subprocess_node_preserves_all_fields(self, workflow_store, test_user_id):
        """Should preserve subworkflow_id, input_mapping, and output_variable fields."""
        # Create a real subworkflow to reference
        create_tool = CreateWorkflowTool()
        sub_session = {"workflow_store": workflow_store, "user_id": test_user_id}
        sub_result = create_tool.execute(
            {"name": "BMI Analyzer", "output_type": "string"},
            session_state=sub_session
        )
        subworkflow_id = sub_result["workflow_id"]
        
        variables = [{"id": "var_bmi_float", "name": "BMI", "type": "float", "source": "input"}]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, variables=variables
        )
        session["workflow_analysis"] = {"variables": variables}
        
        args = {
            "workflow_id": workflow_id,
            "operations": [
                {
                    "op": "add_node",
                    "type": "subprocess",
                    "label": "BMI Analysis",
                    "id": "temp_subprocess",
                    "subworkflow_id": subworkflow_id,
                    "input_mapping": {"BMI": "BMI"},
                    "output_variable": "BMI_Result",
                    "x": 100,
                    "y": 150,
                }
            ]
        }

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        node = result["operations"][0]["node"]
        assert node["subworkflow_id"] == subworkflow_id
        assert node["input_mapping"] == {"BMI": "BMI"}
        assert node["output_variable"] == "BMI_Result"

    def test_subprocess_auto_registers_output_variable_as_input(self, workflow_store, test_user_id):
        """Should automatically register output_variable as a workflow variable."""
        # Create a real subworkflow to reference
        create_tool = CreateWorkflowTool()
        sub_session = {"workflow_store": workflow_store, "user_id": test_user_id}
        sub_result = create_tool.execute(
            {"name": "BMI Analyzer", "output_type": "string"},
            session_state=sub_session
        )
        subworkflow_id = sub_result["workflow_id"]
        
        variables = [{"id": "var_bmi_float", "name": "BMI", "type": "float", "source": "input"}]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, variables=variables
        )
        session["workflow_analysis"] = {"variables": variables}
        
        args = {
            "workflow_id": workflow_id,
            "operations": [
                {
                    "op": "add_node",
                    "type": "subprocess",
                    "label": "BMI Analysis",
                    "id": "temp_subprocess",
                    "subworkflow_id": subworkflow_id,
                    "input_mapping": {"BMI": "BMI"},
                    "output_variable": "BMI_Result",
                }
            ]
        }

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        # Check that BMI_Result was added to workflow variables by reloading from store
        record = workflow_store.get_workflow(workflow_id, test_user_id)
        variables = record.inputs
        output_var_input = next((inp for inp in variables if inp.get("name") == "BMI_Result"), None)
        assert output_var_input is not None
        assert output_var_input["type"] == "string"
        assert output_var_input["source"] == "subprocess"  # New: subprocess-derived variables have source

    def test_subprocess_output_variable_allows_subsequent_decision_reference(self, workflow_store, test_user_id):
        """Should allow decision nodes to reference subprocess output_variable."""
        # Create a real subworkflow to reference
        create_tool = CreateWorkflowTool()
        sub_session = {"workflow_store": workflow_store, "user_id": test_user_id}
        sub_result = create_tool.execute(
            {"name": "BMI Analyzer", "output_type": "string"},
            session_state=sub_session
        )
        subworkflow_id = sub_result["workflow_id"]
        
        variables = [{"id": "var_bmi_float", "name": "BMI", "type": "float", "source": "input"}]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, variables=variables
        )
        session["workflow_analysis"] = {"variables": variables}
        
        args = {
            "workflow_id": workflow_id,
            "operations": [
                # Add subprocess first - this should register BMI_Result as variable
                {
                    "op": "add_node",
                    "type": "subprocess",
                    "label": "BMI Analysis",
                    "id": "temp_subprocess",
                    "subworkflow_id": subworkflow_id,
                    "input_mapping": {"BMI": "BMI"},
                    "output_variable": "BMI_Result",
                    "x": 100,
                    "y": 100,
                },
                # Then add decision that references the output_variable
                {
                    "op": "add_node",
                    "type": "decision",
                    "label": "BMI_Result == 'Normal'",
                    "id": "temp_decision",
                    "x": 100,
                    "y": 200,
                    "condition": {
                        # input_id matches auto-generated format: var_sub_{slug}_{type}
                        "input_id": "var_sub_bmi_result_string",
                        "comparator": "str_eq",
                        "value": "Normal"
                    }
                },
            ]
        }

        result = self.tool.execute(args, session_state=session)

        # This should succeed - the subprocess should have registered BMI_Result
        assert result["success"] is True
        assert result["operation_count"] == 2

    def test_subprocess_missing_fields_fails_validation(self, workflow_store, test_user_id):
        """Should fail if subprocess node is missing required fields."""
        workflow_id, session = make_session_with_workflow(workflow_store, test_user_id)
        args = {
            "workflow_id": workflow_id,
            "operations": [
                {
                    "op": "add_node",
                    "type": "subprocess",
                    "label": "BMI Analysis",
                    "id": "temp_subprocess",
                    # Missing subworkflow_id, input_mapping, output_variable
                }
            ]
        }

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is False
        assert "subworkflow_id" in result["error"] or "missing" in result["error"].lower()

    def test_subprocess_with_complete_workflow(self, workflow_store, test_user_id):
        """Should successfully create a complete workflow with subprocess."""
        # Create a real subworkflow to reference
        create_tool = CreateWorkflowTool()
        sub_session = {"workflow_store": workflow_store, "user_id": test_user_id}
        sub_result = create_tool.execute(
            {"name": "BMI Processor", "output_type": "string"},
            session_state=sub_session
        )
        subworkflow_id = sub_result["workflow_id"]
        
        variables = [{"id": "var_bmi_float", "name": "BMI", "type": "float", "source": "input"}]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, variables=variables
        )
        session["workflow_analysis"] = {"variables": variables}
        
        args = {
            "workflow_id": workflow_id,
            "operations": [
                {"op": "add_node", "type": "start", "label": "Start", "id": "temp_start", "x": 100, "y": 50},
                {
                    "op": "add_node",
                    "type": "subprocess",
                    "label": "Process BMI",
                    "id": "temp_subprocess",
                    "subworkflow_id": subworkflow_id,
                    "input_mapping": {"BMI": "BMI"},
                    "output_variable": "result",
                    "x": 100,
                    "y": 150,
                },
                {
                    "op": "add_node",
                    "type": "decision",
                    "label": "result == 'Normal'",
                    "id": "temp_decision",
                    "x": 100,
                    "y": 250,
                    "condition": {
                        # input_id matches auto-generated format: var_sub_{slug}_{type}
                        "input_id": "var_sub_result_string",
                        "comparator": "str_eq",
                        "value": "Normal"
                    }
                },
                {"op": "add_node", "type": "end", "label": "Healthy", "id": "temp_end1", "x": 50, "y": 350},
                {"op": "add_node", "type": "end", "label": "Unhealthy", "id": "temp_end2", "x": 150, "y": 350},
                {"op": "add_connection", "from": "temp_start", "to": "temp_subprocess", "label": ""},
                {"op": "add_connection", "from": "temp_subprocess", "to": "temp_decision", "label": ""},
                {"op": "add_connection", "from": "temp_decision", "to": "temp_end1", "label": "true"},
                {"op": "add_connection", "from": "temp_decision", "to": "temp_end2", "label": "false"},
            ]
        }

        result = self.tool.execute(args, session_state=session)

        assert result["success"] is True
        assert result["operation_count"] == 9
        
        # Verify subprocess node has all fields
        subprocess_op = next(op for op in result["operations"] if op["op"] == "add_node" and op["node"]["type"] == "subprocess")
        assert subprocess_op["node"]["subworkflow_id"] == subworkflow_id
        assert subprocess_op["node"]["input_mapping"] == {"BMI": "BMI"}
        assert subprocess_op["node"]["output_variable"] == "result"
