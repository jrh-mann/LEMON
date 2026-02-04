"""Tests for decision node edge label enforcement.

Decision nodes MUST have exactly two outgoing edges with labels "true" and "false".
This ensures the workflow interpreter correctly routes execution based on condition results.
"""

import pytest
from src.backend.tools.workflow_edit import BatchEditWorkflowTool
from src.backend.tools.workflow_edit.add_connection import AddConnectionTool
from tests.conftest import make_session_with_workflow


class TestDecisionEdgeLabelEnforcement:
    """Test that decision node edges are properly labeled with true/false."""

    def setup_method(self):
        self.batch_tool = BatchEditWorkflowTool()
        self.add_connection_tool = AddConnectionTool()

    def _create_decision_workflow(self, workflow_store, test_user_id):
        """Helper to create a workflow with a decision node and end nodes."""
        nodes = [
            {"id": "start_1", "type": "start", "label": "Input", "x": 0, "y": 0, "color": "teal"},
            {"id": "decision_1", "type": "decision", "label": "Check Value", "x": 100, "y": 0, "color": "amber",
             "condition": {"input_id": "var_value_number", "comparator": "gt", "value": 10}},
            {"id": "end_true", "type": "end", "label": "Greater", "x": 50, "y": 100, "color": "green"},
            {"id": "end_false", "type": "end", "label": "Not Greater", "x": 150, "y": 100, "color": "green"},
        ]
        edges = [
            {"id": "start_1->decision_1", "from": "start_1", "to": "decision_1", "label": ""},
        ]
        variables = [{"id": "var_value_number", "name": "value", "type": "number", "source": "input"}]
        
        return make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, edges=edges, variables=variables
        )

    # --- add_connection tool tests ---

    def test_add_connection_auto_assigns_true_for_first_decision_edge(self, workflow_store, test_user_id):
        """When adding first edge from decision without label, should auto-assign 'true'."""
        workflow_id, session = self._create_decision_workflow(workflow_store, test_user_id)
        
        # Add first edge without label
        result = self.add_connection_tool.execute({
            "workflow_id": workflow_id,
            "from_node_id": "decision_1",
            "to_node_id": "end_true",
            # No label provided
        }, session_state=session)
        
        assert result["success"] is True
        assert result["edge"]["label"] == "true"

    def test_add_connection_auto_assigns_false_for_second_decision_edge(self, workflow_store, test_user_id):
        """When adding second edge from decision without label, should auto-assign 'false'."""
        # Create workflow with one existing edge from decision
        nodes = [
            {"id": "decision_1", "type": "decision", "label": "Check", "x": 100, "y": 0, "color": "amber",
             "condition": {"input_id": "var_value_number", "comparator": "gt", "value": 10}},
            {"id": "end_true", "type": "end", "label": "True Path", "x": 50, "y": 100, "color": "green"},
            {"id": "end_false", "type": "end", "label": "False Path", "x": 150, "y": 100, "color": "green"},
        ]
        edges = [
            # Already has a 'true' edge
            {"id": "decision_1->end_true", "from": "decision_1", "to": "end_true", "label": "true"},
        ]
        variables = [{"id": "var_value_number", "name": "value", "type": "number", "source": "input"}]
        
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, edges=edges, variables=variables
        )
        
        # Add second edge without label
        result = self.add_connection_tool.execute({
            "workflow_id": workflow_id,
            "from_node_id": "decision_1",
            "to_node_id": "end_false",
            # No label provided
        }, session_state=session)
        
        assert result["success"] is True
        assert result["edge"]["label"] == "false"

    def test_add_connection_rejects_invalid_decision_edge_label(self, workflow_store, test_user_id):
        """When providing invalid label for decision edge, should reject."""
        workflow_id, session = self._create_decision_workflow(workflow_store, test_user_id)
        
        result = self.add_connection_tool.execute({
            "workflow_id": workflow_id,
            "from_node_id": "decision_1",
            "to_node_id": "end_true",
            "label": "maybe",  # Invalid label
        }, session_state=session)
        
        assert result["success"] is False
        assert result["error_code"] == "INVALID_EDGE_LABEL"
        assert "true" in result["error"].lower() or "false" in result["error"].lower()

    def test_add_connection_rejects_duplicate_decision_edge_label(self, workflow_store, test_user_id):
        """When trying to add duplicate label for decision edge, should reject."""
        nodes = [
            {"id": "decision_1", "type": "decision", "label": "Check", "x": 100, "y": 0, "color": "amber",
             "condition": {"input_id": "var_value_number", "comparator": "gt", "value": 10}},
            {"id": "end_1", "type": "end", "label": "Path 1", "x": 50, "y": 100, "color": "green"},
            {"id": "end_2", "type": "end", "label": "Path 2", "x": 150, "y": 100, "color": "green"},
        ]
        edges = [
            {"id": "decision_1->end_1", "from": "decision_1", "to": "end_1", "label": "true"},
        ]
        variables = [{"id": "var_value_number", "name": "value", "type": "number", "source": "input"}]
        
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, edges=edges, variables=variables
        )
        
        # Try to add another "true" edge
        result = self.add_connection_tool.execute({
            "workflow_id": workflow_id,
            "from_node_id": "decision_1",
            "to_node_id": "end_2",
            "label": "true",  # Duplicate
        }, session_state=session)
        
        assert result["success"] is False
        assert result["error_code"] == "DUPLICATE_EDGE_LABEL"

    def test_add_connection_rejects_third_decision_edge(self, workflow_store, test_user_id):
        """When trying to add third edge from decision, should reject."""
        nodes = [
            {"id": "decision_1", "type": "decision", "label": "Check", "x": 100, "y": 0, "color": "amber",
             "condition": {"input_id": "var_value_number", "comparator": "gt", "value": 10}},
            {"id": "end_1", "type": "end", "label": "Path 1", "x": 50, "y": 100, "color": "green"},
            {"id": "end_2", "type": "end", "label": "Path 2", "x": 150, "y": 100, "color": "green"},
            {"id": "end_3", "type": "end", "label": "Path 3", "x": 200, "y": 100, "color": "green"},
        ]
        edges = [
            {"id": "decision_1->end_1", "from": "decision_1", "to": "end_1", "label": "true"},
            {"id": "decision_1->end_2", "from": "decision_1", "to": "end_2", "label": "false"},
        ]
        variables = [{"id": "var_value_number", "name": "value", "type": "number", "source": "input"}]
        
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, edges=edges, variables=variables
        )
        
        # Try to add third edge
        result = self.add_connection_tool.execute({
            "workflow_id": workflow_id,
            "from_node_id": "decision_1",
            "to_node_id": "end_3",
            # No label - auto-assign would fail as both are taken
        }, session_state=session)
        
        assert result["success"] is False
        assert result["error_code"] == "MAX_BRANCHES_REACHED"

    def test_add_connection_normalizes_label_to_lowercase(self, workflow_store, test_user_id):
        """Edge labels should be normalized to lowercase."""
        workflow_id, session = self._create_decision_workflow(workflow_store, test_user_id)
        
        result = self.add_connection_tool.execute({
            "workflow_id": workflow_id,
            "from_node_id": "decision_1",
            "to_node_id": "end_true",
            "label": "TRUE",  # Uppercase
        }, session_state=session)
        
        assert result["success"] is True
        assert result["edge"]["label"] == "true"  # Should be lowercase

    # --- batch_edit tool tests ---

    def test_batch_edit_auto_assigns_decision_edge_labels(self, workflow_store, test_user_id):
        """Batch edit should auto-assign true/false labels for decision edges."""
        nodes = [
            {"id": "start_1", "type": "start", "label": "Input", "x": 0, "y": 0, "color": "teal"},
        ]
        variables = [{"id": "var_value_number", "name": "value", "type": "number", "source": "input"}]
        
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, variables=variables
        )
        session["workflow_analysis"] = {"variables": variables}
        
        result = self.batch_tool.execute({
            "workflow_id": workflow_id,
            "operations": [
                {"op": "add_node", "type": "decision", "label": "Check", "id": "temp_decision",
                 "condition": {"input_id": "var_value_number", "comparator": "gt", "value": 10}},
                {"op": "add_node", "type": "end", "label": "True", "id": "temp_true"},
                {"op": "add_node", "type": "end", "label": "False", "id": "temp_false"},
                {"op": "add_connection", "from": "start_1", "to": "temp_decision"},
                # No labels provided - should auto-assign
                {"op": "add_connection", "from": "temp_decision", "to": "temp_true"},
                {"op": "add_connection", "from": "temp_decision", "to": "temp_false"},
            ]
        }, session_state=session)
        
        assert result["success"] is True
        
        # Find the decision edges in the operations
        # The decision node was added with temp_id "temp_decision" which was mapped to a real ID
        edge_ops = [op for op in result["operations"] if op["op"] == "add_connection"]
        
        # Find the real decision node ID by looking at add_node operations
        add_node_ops = [op for op in result["operations"] if op["op"] == "add_node"]
        decision_node_op = next(op for op in add_node_ops if op["node"]["type"] == "decision")
        decision_node_id = decision_node_op["node"]["id"]
        
        # Find edges from the decision node
        decision_edges = [
            op["edge"] for op in edge_ops 
            if op["edge"]["from"] == decision_node_id
        ]
        
        # Should have assigned true and false
        labels = {e["label"] for e in decision_edges}
        assert labels == {"true", "false"}

    def test_batch_edit_rejects_invalid_decision_edge_label(self, workflow_store, test_user_id):
        """Batch edit should reject invalid labels for decision edges."""
        nodes = [
            {"id": "start_1", "type": "start", "label": "Input", "x": 0, "y": 0, "color": "teal"},
        ]
        variables = [{"id": "var_value_number", "name": "value", "type": "number", "source": "input"}]
        
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, variables=variables
        )
        session["workflow_analysis"] = {"variables": variables}
        
        result = self.batch_tool.execute({
            "workflow_id": workflow_id,
            "operations": [
                {"op": "add_node", "type": "decision", "label": "Check", "id": "temp_decision",
                 "condition": {"input_id": "var_value_number", "comparator": "gt", "value": 10}},
                {"op": "add_node", "type": "end", "label": "End", "id": "temp_end"},
                {"op": "add_connection", "from": "temp_decision", "to": "temp_end", "label": "maybe"},
            ]
        }, session_state=session)
        
        assert result["success"] is False
        assert "true" in result["error"].lower() or "false" in result["error"].lower()

    def test_batch_edit_modify_connection_changes_label(self, workflow_store, test_user_id):
        """Batch edit modify_connection should change edge label."""
        nodes = [
            {"id": "decision_1", "type": "decision", "label": "Check", "x": 100, "y": 0, "color": "amber",
             "condition": {"input_id": "var_value_number", "comparator": "gt", "value": 10}},
            {"id": "end_1", "type": "end", "label": "Path 1", "x": 50, "y": 100, "color": "green"},
        ]
        edges = [
            # Only one edge, labeled true
            {"id": "decision_1->end_1", "from": "decision_1", "to": "end_1", "label": "true"},
        ]
        variables = [{"id": "var_value_number", "name": "value", "type": "number", "source": "input"}]
        
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, edges=edges, variables=variables
        )
        
        # Change the label from true to false
        result = self.batch_tool.execute({
            "workflow_id": workflow_id,
            "operations": [
                {"op": "modify_connection", "from": "decision_1", "to": "end_1", "label": "false"},
            ]
        }, session_state=session)
        
        assert result["success"] is True
        
        # Verify the workflow was updated
        workflow_record = workflow_store.get_workflow(workflow_id, test_user_id)
        edge_labels = {f"{e['from']}->{e['to']}": e["label"] for e in workflow_record.edges}
        
        assert edge_labels["decision_1->end_1"] == "false"

    def test_batch_edit_modify_connection_rejects_invalid_label(self, workflow_store, test_user_id):
        """Modify connection should reject invalid labels for decision edges."""
        nodes = [
            {"id": "decision_1", "type": "decision", "label": "Check", "x": 100, "y": 0, "color": "amber",
             "condition": {"input_id": "var_value_number", "comparator": "gt", "value": 10}},
            {"id": "end_1", "type": "end", "label": "Path 1", "x": 50, "y": 100, "color": "green"},
        ]
        edges = [
            {"id": "decision_1->end_1", "from": "decision_1", "to": "end_1", "label": "true"},
        ]
        variables = [{"id": "var_value_number", "name": "value", "type": "number", "source": "input"}]
        
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, edges=edges, variables=variables
        )
        
        result = self.batch_tool.execute({
            "workflow_id": workflow_id,
            "operations": [
                {"op": "modify_connection", "from": "decision_1", "to": "end_1", "label": "maybe"},
            ]
        }, session_state=session)
        
        assert result["success"] is False
        assert "true" in result["error"].lower() or "false" in result["error"].lower()

    def test_batch_edit_modify_connection_rejects_duplicate_label(self, workflow_store, test_user_id):
        """Modify connection should reject changing to a label that already exists."""
        nodes = [
            {"id": "decision_1", "type": "decision", "label": "Check", "x": 100, "y": 0, "color": "amber",
             "condition": {"input_id": "var_value_number", "comparator": "gt", "value": 10}},
            {"id": "end_1", "type": "end", "label": "Path 1", "x": 50, "y": 100, "color": "green"},
            {"id": "end_2", "type": "end", "label": "Path 2", "x": 150, "y": 100, "color": "green"},
        ]
        edges = [
            {"id": "decision_1->end_1", "from": "decision_1", "to": "end_1", "label": "true"},
            {"id": "decision_1->end_2", "from": "decision_1", "to": "end_2", "label": "false"},
        ]
        variables = [{"id": "var_value_number", "name": "value", "type": "number", "source": "input"}]
        
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, edges=edges, variables=variables
        )
        
        # Try to change false edge to true (which already exists)
        result = self.batch_tool.execute({
            "workflow_id": workflow_id,
            "operations": [
                {"op": "modify_connection", "from": "decision_1", "to": "end_2", "label": "true"},
            ]
        }, session_state=session)
        
        assert result["success"] is False
        assert "already has" in result["error"].lower()
