"""Tests for ValidateWorkflowTool.

All workflow tools now require workflow_id parameter - workflows must be created first
using create_workflow, then tools operate on them by ID with auto-save to database.
"""

import pytest
from src.backend.tools.validate_workflow import ValidateWorkflowTool
from src.backend.tools.workflow_edit.delete_connection import DeleteConnectionTool
from src.backend.tools.workflow_edit.add_connection import AddConnectionTool
from src.backend.tools.workflow_edit.delete_node import DeleteNodeTool
from tests.conftest import make_session_with_workflow


class TestValidateWorkflowTool:
    def setup_method(self):
        self.tool = ValidateWorkflowTool()

    def test_validate_valid_workflow(self, workflow_store, test_user_id):
        """Should return valid=True for a complete connected workflow"""
        nodes = [
            {"id": "n1", "type": "start", "label": "Start", "x": 0, "y": 0},
            {"id": "n2", "type": "end", "label": "End", "x": 100, "y": 0},
        ]
        edges = [
            {"id": "e1", "from": "n1", "to": "n2", "label": ""}
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, edges=edges
        )
        
        result = self.tool.execute({"workflow_id": workflow_id}, session_state=session)
        
        assert result["success"] is True
        assert result["valid"] is True
        assert "message" in result

    def test_validate_disconnected_workflow(self, workflow_store, test_user_id):
        """Should return valid=False for disconnected workflow (unreachable node)"""
        nodes = [
            {"id": "n1", "type": "start", "label": "Start", "x": 0, "y": 0},
            {"id": "n2", "type": "end", "label": "End", "x": 100, "y": 0},
            {"id": "n3", "type": "process", "label": "Isolated", "x": 50, "y": 50},
        ]
        edges = [
            {"id": "e1", "from": "n1", "to": "n2", "label": ""}
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, edges=edges
        )
        
        result = self.tool.execute({"workflow_id": workflow_id}, session_state=session)
        
        assert result["success"] is True
        assert result["valid"] is False
        assert len(result["errors"]) > 0
        assert any(e["code"] == "UNREACHABLE_NODE" for e in result["errors"])
        assert "Isolated" in result["message"]

    def test_validate_incomplete_decision(self, workflow_store, test_user_id):
        """Should return valid=False for decision node with insufficient branches"""
        nodes = [
            {"id": "n1", "type": "decision", "label": "Check?", "x": 0, "y": 0},
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes
        )
        
        result = self.tool.execute({"workflow_id": workflow_id}, session_state=session)
        
        assert result["success"] is True
        assert result["valid"] is False
        assert any(e["code"] == "DECISION_NEEDS_BRANCHES" for e in result["errors"])

    def test_validate_with_subprocess_variables(self, workflow_store, test_user_id):
        """Should recognize subprocess-derived variables when validating decision nodes.
        
        Regression test for: Decision nodes referencing subprocess output variables
        were failing validation with 'references unknown variable id' error because
        validate_workflow.py was reading from 'inputs' instead of 'variables'.
        """
        nodes = [
            {"id": "n1", "type": "start", "label": "Start", "x": 0, "y": 0},
            {"id": "n2", "type": "subprocess", "label": "Calculate BMI", "x": 100, "y": 0,
             "subworkflow_id": "some_workflow", "output_variable": "BMI",
             "input_mapping": {"Height": "height_input"}},  # Required field
            {"id": "n3", "type": "decision", "label": "BMI < 25?", "x": 200, "y": 0,
             "condition": {"input_id": "var_sub_bmi_float", "comparator": "lt", "value": 25}},
            {"id": "n4", "type": "end", "label": "Normal", "x": 300, "y": -50},
            {"id": "n5", "type": "end", "label": "Overweight", "x": 300, "y": 50},
        ]
        edges = [
            {"id": "e1", "from": "n1", "to": "n2", "label": ""},
            {"id": "e2", "from": "n2", "to": "n3", "label": ""},
            {"id": "e3", "from": "n3", "to": "n4", "label": "true"},
            {"id": "e4", "from": "n3", "to": "n5", "label": "false"},
        ]
        variables = [
            {"id": "var_height_float", "name": "Height", "type": "number", "source": "input"},
            {"id": "var_sub_bmi_float", "name": "BMI", "type": "number", "source": "subprocess",
             "source_node_id": "n2", "subworkflow_id": "some_workflow"},
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, edges=edges, variables=variables
        )
        # Also add workflow_analysis to session for validator to read from
        session["workflow_analysis"] = {
            "variables": variables,
            "outputs": [],
            "tree": {},
            "doubts": [],
        }
        
        result = self.tool.execute({"workflow_id": workflow_id}, session_state=session)
        
        assert result["success"] is True
        # Should be valid since var_sub_bmi_float exists in variables
        assert result["valid"] is True, f"Validation failed: {result.get('message')}"


class TestEditToolsPassVariables:
    """Tests ensuring edit tools pass variables to validator for template validation."""

    def test_delete_connection_with_output_template_variables(self, workflow_store, test_user_id):
        """delete_connection should pass variables so output templates validate correctly.
        
        Regression test for: delete_connection was showing 'Available variables: []'
        because it wasn't passing variables to the validator.
        """
        tool = DeleteConnectionTool()
        nodes = [
            {"id": "n1", "type": "start", "label": "Start", "x": 0, "y": 0},
            {"id": "n2", "type": "process", "label": "Process", "x": 100, "y": 0},
            {"id": "n3", "type": "end", "label": "Result", "x": 200, "y": 0,
             "output_template": "BMI is {BMI}"},
        ]
        edges = [
            {"id": "e1", "from": "n1", "to": "n2", "label": ""},
            {"id": "e2", "from": "n2", "to": "n3", "label": ""},
        ]
        variables = [
            {"id": "var_bmi_float", "name": "BMI", "type": "number", "source": "subprocess"},
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, edges=edges, variables=variables
        )
        # Add workflow_analysis to session for validator
        session["workflow_analysis"] = {
            "variables": variables,
            "outputs": [],
            "tree": {},
            "doubts": [],
        }
        
        # Delete the edge from n1 to n2 - this should validate with template vars
        result = tool.execute(
            {"workflow_id": workflow_id, "from_node_id": "n1", "to_node_id": "n2"},
            session_state=session
        )
        
        # Should succeed because BMI is a known variable
        assert result["success"] is True, f"Failed: {result.get('error')}"
        
    def test_delete_connection_fails_with_unknown_template_var(self, workflow_store, test_user_id):
        """delete_connection should show available variables when template validation fails."""
        tool = DeleteConnectionTool()
        nodes = [
            {"id": "n1", "type": "start", "label": "Start", "x": 0, "y": 0},
            {"id": "n2", "type": "process", "label": "Process", "x": 100, "y": 0},
            {"id": "n3", "type": "end", "label": "Result", "x": 200, "y": 0,
             "output_template": "Unknown is {UnknownVar}"},
        ]
        edges = [
            {"id": "e1", "from": "n1", "to": "n2", "label": ""},
            {"id": "e2", "from": "n2", "to": "n3", "label": ""},
        ]
        variables = [
            {"id": "var_bmi_float", "name": "BMI", "type": "number", "source": "subprocess"},
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, edges=edges, variables=variables
        )
        session["workflow_analysis"] = {
            "variables": variables,
            "outputs": [],
            "tree": {},
            "doubts": [],
        }
        
        result = tool.execute(
            {"workflow_id": workflow_id, "from_node_id": "n1", "to_node_id": "n2"},
            session_state=session
        )
        
        # Should fail because UnknownVar is not a known variable
        assert result["success"] is False
        # Should list available variables (not empty list)
        assert "BMI" in result["error"], f"Should show BMI in available vars: {result['error']}"

    def test_add_connection_passes_variables(self, workflow_store, test_user_id):
        """add_connection should pass variables to validator."""
        tool = AddConnectionTool()
        nodes = [
            {"id": "n1", "type": "start", "label": "Start", "x": 0, "y": 0},
            {"id": "n2", "type": "end", "label": "Result", "x": 100, "y": 0,
             "output_template": "BMI is {BMI}"},
        ]
        variables = [
            {"id": "var_bmi_float", "name": "BMI", "type": "number", "source": "subprocess"},
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, variables=variables
        )
        session["workflow_analysis"] = {
            "variables": variables,
            "outputs": [],
            "tree": {},
            "doubts": [],
        }
        
        result = tool.execute(
            {"workflow_id": workflow_id, "from_node_id": "n1", "to_node_id": "n2"},
            session_state=session
        )
        
        # Should succeed because BMI is a known variable
        assert result["success"] is True, f"Failed: {result.get('error')}"

    def test_delete_node_passes_variables(self, workflow_store, test_user_id):
        """delete_node should pass variables to validator."""
        tool = DeleteNodeTool()
        nodes = [
            {"id": "n1", "type": "start", "label": "Start", "x": 0, "y": 0},
            {"id": "n2", "type": "process", "label": "Middle", "x": 100, "y": 0},
            {"id": "n3", "type": "end", "label": "Result", "x": 200, "y": 0,
             "output_template": "BMI is {BMI}"},
        ]
        edges = [
            {"id": "e1", "from": "n1", "to": "n2", "label": ""},
            {"id": "e2", "from": "n2", "to": "n3", "label": ""},
        ]
        variables = [
            {"id": "var_bmi_float", "name": "BMI", "type": "number", "source": "subprocess"},
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, edges=edges, variables=variables
        )
        session["workflow_analysis"] = {
            "variables": variables,
            "outputs": [],
            "tree": {},
            "doubts": [],
        }
        
        # Delete middle node - validation should still see BMI variable
        result = tool.execute(
            {"workflow_id": workflow_id, "node_id": "n2"},
            session_state=session
        )
        
        # Should succeed because BMI is a known variable
        assert result["success"] is True, f"Failed: {result.get('error')}"
