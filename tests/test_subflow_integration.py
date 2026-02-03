"""Integration tests for subflow execution through the API and tools.

All workflow tools now require workflow_id parameter - workflows must be created first
using create_workflow, then tools operate on them by ID with auto-save to database.

Tests the full flow:
1. Creating subprocess nodes via tools
2. Workflow validation with subprocess nodes
3. Execution through TreeInterpreter with WorkflowStore
"""

import pytest
from unittest.mock import Mock, MagicMock, patch

from src.backend.tools.workflow_edit import AddNodeTool, ModifyNodeTool
from src.backend.tools.workflow_edit.get_current import GetCurrentWorkflowTool
from src.backend.validation.workflow_validator import WorkflowValidator
from src.backend.execution.interpreter import TreeInterpreter
from tests.conftest import make_session_with_workflow


# =============================================================================
# MOCK WORKFLOW STORE (for interpreter execution tests only)
# =============================================================================

class MockWorkflowStore:
    """Mock WorkflowStore for testing subflow execution."""
    
    def __init__(self, workflows: dict = None):
        self.workflows = workflows or {}
    
    def get_workflow(self, workflow_id: str, user_id: str):
        return self.workflows.get(workflow_id)


class MockWorkflow:
    """Mock workflow object with required attributes."""
    
    def __init__(self, name: str, tree: dict, inputs: list, outputs: list):
        self.name = name
        self.tree = tree
        self.inputs = inputs
        self.outputs = outputs


# =============================================================================
# TEST FIXTURES
# =============================================================================

# Simple subworkflow for testing
SIMPLE_SUBWORKFLOW = MockWorkflow(
    name="Simple Calculator",
    inputs=[
        {"id": "input_x_int", "name": "X", "type": "int", "range": {"min": 0, "max": 100}}
    ],
    outputs=[{"name": "Result", "type": "string"}],  # Added type field
    tree={
        "start": {
            "id": "start",
            "type": "start",
            "label": "Start",
            "children": [
                {
                    "id": "check",
                    "type": "decision",
                    "label": "X >= 50",
                    "condition": {
                        "input_id": "input_x_int",
                        "comparator": "gte",
                        "value": 50
                    },
                    "children": [
                        {
                            "id": "out_high",
                            "type": "output",
                            "label": "High",
                            "output_type": "string",
                            "output_value": "High",
                            "edge_label": "Yes",
                            "children": []
                        },
                        {
                            "id": "out_low",
                            "type": "output",
                            "label": "Low",
                            "output_type": "string",
                            "output_value": "Low",
                            "edge_label": "No",
                            "children": []
                        }
                    ]
                }
            ]
        }
    }
)


# =============================================================================
# TOOL INTEGRATION TESTS
# =============================================================================

class TestAddSubprocessNodeTool:
    """Test AddNodeTool with subprocess nodes."""

    def setup_method(self):
        self.add_node_tool = AddNodeTool()
    
    def test_add_subprocess_node_success(self, workflow_store, test_user_id):
        """Test successfully adding a subprocess node."""
        # Create a mock subworkflow to reference
        from src.backend.tools import CreateWorkflowTool
        create_tool = CreateWorkflowTool()
        session = {"workflow_store": workflow_store, "user_id": test_user_id}
        
        # Create subworkflow
        sub_result = create_tool.execute(
            {"name": "Simple Calculator", "output_type": "string"},
            session_state=session
        )
        subworkflow_id = sub_result["workflow_id"]
        
        # Create main workflow with a variable to map
        variables = [
            {"id": "var_value_int", "name": "Value", "type": "int", "source": "input"}
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, variables=variables
        )
        session["workflow_analysis"] = {
            "variables": variables
        }
        
        result = self.add_node_tool.execute({
            "workflow_id": workflow_id,
            "type": "subprocess",
            "label": "Calculate Result",
            "subworkflow_id": subworkflow_id,
            "input_mapping": {"Value": "X"},
            "output_variable": "Result",
        }, session_state=session)
        
        assert result["success"] is True
        assert result["node"]["type"] == "subprocess"
        assert result["node"]["subworkflow_id"] == subworkflow_id
        assert result["node"]["input_mapping"] == {"Value": "X"}
        assert result["node"]["output_variable"] == "Result"
    
    def test_add_subprocess_node_missing_subworkflow_id(self, workflow_store, test_user_id):
        """Test that subprocess without subworkflow_id fails validation."""
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id
        )
        
        result = self.add_node_tool.execute({
            "workflow_id": workflow_id,
            "type": "subprocess",
            "label": "Missing ID",
            # No subworkflow_id
            "input_mapping": {},
            "output_variable": "Result",
        }, session_state=session)
        
        assert result["success"] is False
        assert "subworkflow_id" in result["error"].lower()
    
    def test_add_subprocess_node_missing_output_variable(self, workflow_store, test_user_id):
        """Test that subprocess without output_variable fails validation."""
        # Create a subworkflow to reference
        from src.backend.tools import CreateWorkflowTool
        create_tool = CreateWorkflowTool()
        session = {"workflow_store": workflow_store, "user_id": test_user_id}
        
        sub_result = create_tool.execute(
            {"name": "Subworkflow", "output_type": "string"},
            session_state=session
        )
        subworkflow_id = sub_result["workflow_id"]
        
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id
        )
        
        result = self.add_node_tool.execute({
            "workflow_id": workflow_id,
            "type": "subprocess",
            "label": "Missing Output",
            "subworkflow_id": subworkflow_id,
            "input_mapping": {},
            # No output_variable
        }, session_state=session)
        
        assert result["success"] is False
        assert "output_variable" in result["error"].lower()
    
    def test_add_subprocess_node_invalid_input_mapping(self, workflow_store, test_user_id):
        """Test that subprocess with invalid input_mapping fails validation."""
        # Create a subworkflow to reference
        from src.backend.tools import CreateWorkflowTool
        create_tool = CreateWorkflowTool()
        session = {"workflow_store": workflow_store, "user_id": test_user_id}
        
        sub_result = create_tool.execute(
            {"name": "Subworkflow", "output_type": "string"},
            session_state=session
        )
        subworkflow_id = sub_result["workflow_id"]
        
        variables = [
            {"id": "input_value_int", "name": "Value", "type": "int", "source": "input"}
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, variables=variables
        )
        session["workflow_analysis"] = {"variables": variables}
        
        result = self.add_node_tool.execute({
            "workflow_id": workflow_id,
            "type": "subprocess",
            "label": "Invalid Mapping",
            "subworkflow_id": subworkflow_id,
            "input_mapping": {"NonExistent": "X"},  # NonExistent is not a valid input
            "output_variable": "Result",
        }, session_state=session)
        
        assert result["success"] is False
        assert "input" in result["error"].lower()


class TestModifySubprocessNodeTool:
    """Test ModifyNodeTool with subprocess nodes."""

    def setup_method(self):
        self.modify_node_tool = ModifyNodeTool()
    
    def test_modify_subprocess_node(self, workflow_store, test_user_id):
        """Test modifying a subprocess node."""
        # Create a subworkflow to reference
        from src.backend.tools import CreateWorkflowTool
        create_tool = CreateWorkflowTool()
        session = {"workflow_store": workflow_store, "user_id": test_user_id}
        
        sub_result = create_tool.execute(
            {"name": "Subworkflow", "output_type": "string"},
            session_state=session
        )
        subworkflow_id = sub_result["workflow_id"]
        
        # Create main workflow with subprocess node
        nodes = [
            {
                "id": "sub_1",
                "type": "subprocess",
                "label": "Old Label",
                "x": 100, "y": 100,
                "color": "rose",
                "subworkflow_id": subworkflow_id,
                "input_mapping": {},
                "output_variable": "OldResult",
            }
        ]
        variables = [
            {"id": "var_val_int", "name": "Val", "type": "int", "source": "input"}
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes, variables=variables
        )
        session["workflow_analysis"] = {"variables": variables}
        
        result = self.modify_node_tool.execute({
            "workflow_id": workflow_id,
            "node_id": "sub_1",
            "label": "New Label",
            "input_mapping": {"Val": "X"},
            "output_variable": "NewResult",
        }, session_state=session)
        
        assert result["success"] is True
        assert result["node"]["label"] == "New Label"
        assert result["node"]["input_mapping"] == {"Val": "X"}
        assert result["node"]["output_variable"] == "NewResult"


class TestGetCurrentWorkflowWithSubprocess:
    """Test GetCurrentWorkflowTool displays subprocess info."""

    def setup_method(self):
        self.get_workflow_tool = GetCurrentWorkflowTool()
    
    def test_get_workflow_shows_subprocess_info(self, workflow_store, test_user_id):
        """Test that subprocess node info is displayed."""
        nodes = [
            {
                "id": "sub_1",
                "type": "subprocess",
                "label": "Credit Check",
                "x": 100, "y": 100,
                "color": "rose",
                "subworkflow_id": "wf_credit",
                "input_mapping": {"Income": "Salary"},
                "output_variable": "Score",
            }
        ]
        workflow_id, session = make_session_with_workflow(
            workflow_store, test_user_id, nodes=nodes
        )
        
        result = self.get_workflow_tool.execute(
            {"workflow_id": workflow_id},
            session_state=session
        )
        
        assert result["success"] is True
        
        # Check that subprocess info is in the summary
        node_descriptions = result["summary"]["node_descriptions"]
        assert "subprocess" in node_descriptions
        assert "calls=wf_credit" in node_descriptions
        assert "output_as=Score" in node_descriptions


class TestWorkflowValidatorSubprocess:
    """Test workflow validator with subprocess nodes."""

    def setup_method(self):
        self.validator = WorkflowValidator()
    
    def test_validator_accepts_valid_subprocess(self):
        """Test validator accepts valid subprocess configuration."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0, "color": "teal"},
                {
                    "id": "sub_1",
                    "type": "subprocess",
                    "label": "Process",
                    "x": 100, "y": 100,
                    "color": "rose",
                    "subworkflow_id": "wf_sub",
                    "input_mapping": {},
                    "output_variable": "Result",
                },
                {"id": "end", "type": "end", "label": "Done", "x": 200, "y": 200, "color": "green"},
            ],
            "edges": [
                {"from": "start", "to": "sub_1", "label": ""},
                {"from": "sub_1", "to": "end", "label": ""},
            ]
        }
        
        is_valid, errors = self.validator.validate(workflow, strict=False)
        
        # Subprocess structure should be valid
        # (Note: may still have other validation issues like missing inputs)
        subprocess_errors = [e for e in errors if "subprocess" in e.message.lower()]
        assert len(subprocess_errors) == 0
    
    def test_validator_rejects_subprocess_missing_fields(self):
        """Test validator rejects subprocess missing required fields."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0, "color": "teal"},
                {
                    "id": "sub_1",
                    "type": "subprocess",
                    "label": "Process",
                    "x": 100, "y": 100,
                    "color": "rose",
                    # Missing: subworkflow_id, input_mapping, output_variable
                },
                {"id": "end", "type": "end", "label": "Done", "x": 200, "y": 200, "color": "green"},
            ],
            "edges": [
                {"from": "start", "to": "sub_1", "label": ""},
                {"from": "sub_1", "to": "end", "label": ""},
            ]
        }
        
        is_valid, errors = self.validator.validate(workflow, strict=True)
        
        # Should have errors about missing subprocess fields
        assert is_valid is False
        subprocess_errors = [e for e in errors if "subprocess" in e.message.lower() or 
                           "subworkflow_id" in e.message.lower() or
                           "output_variable" in e.message.lower()]
        assert len(subprocess_errors) > 0


class TestSubflowExecutionIntegration:
    """Integration test for full subflow execution flow."""

    def test_full_subflow_execution(self):
        """Test end-to-end subflow execution."""
        # Create workflow store with the subworkflow
        workflow_store = MockWorkflowStore({
            "wf_simple": SIMPLE_SUBWORKFLOW
        })
        
        # Parent workflow that calls the subworkflow
        parent_tree = {
            "start": {
                "id": "start",
                "type": "start",
                "label": "Start",
                "children": [
                    {
                        "id": "call_sub",
                        "type": "subprocess",
                        "label": "Call Simple",
                        "subworkflow_id": "wf_simple",
                        "input_mapping": {"Value": "X"},
                        "output_variable": "SubResult",
                        "children": [
                            {
                                "id": "check_result",
                                "type": "decision",
                                "label": "SubResult == 'High'",
                                "condition": {
                                    "input_id": "var_sub_subresult_string",
                                    "comparator": "str_eq",
                                    "value": "High"
                                },
                                "children": [
                                    {
                                        "id": "out_approved",
                                        "type": "output",
                                        "label": "Approved",
                                        "edge_label": "Yes",
                                        "children": []
                                    },
                                    {
                                        "id": "out_denied",
                                        "type": "output",
                                        "label": "Denied",
                                        "edge_label": "No",
                                        "children": []
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        }
        
        parent_inputs = [
            {"id": "input_value_int", "name": "Value", "type": "int", "range": {"min": 0, "max": 100}}
        ]
        parent_outputs = [{"name": "Approved"}, {"name": "Denied"}]
        
        # Test case 1: High value (>= 50) should result in "Approved"
        interpreter = TreeInterpreter(
            tree=parent_tree,
            inputs=parent_inputs,
            outputs=parent_outputs,
            workflow_id="wf_parent",
            workflow_store=workflow_store,
            user_id="test_user",
        )
        
        result = interpreter.execute({"input_value_int": 75})
        
        assert result.success is True
        assert result.output == "Approved"
        assert len(result.subflow_results) == 1
        assert result.subflow_results[0]["result"]["output"] == "High"
        
        # Test case 2: Low value (< 50) should result in "Denied"
        interpreter2 = TreeInterpreter(
            tree=parent_tree,
            inputs=parent_inputs,
            outputs=parent_outputs,
            workflow_id="wf_parent",
            workflow_store=workflow_store,
            user_id="test_user",
        )
        
        result2 = interpreter2.execute({"input_value_int": 25})
        
        assert result2.success is True
        assert result2.output == "Denied"
        assert len(result2.subflow_results) == 1
        assert result2.subflow_results[0]["result"]["output"] == "Low"
    
    def test_nested_subflow_execution(self):
        """Test subflow that calls another subflow (nested)."""
        # Level 2 subworkflow (innermost)
        level2_workflow = MockWorkflow(
            name="Level 2",
            inputs=[{"id": "input_n_int", "name": "N", "type": "int", "range": {"min": 0, "max": 100}}],
            outputs=[{"name": "L2Result"}],
            tree={
                "start": {
                    "id": "start",
                    "type": "start",
                    "children": [
                        {
                            "id": "out",
                            "type": "output",
                            "label": "Done",
                            "output_type": "int",
                            "output_value": 42,
                            "children": []
                        }
                    ]
                }
            }
        )
        
        # Level 1 subworkflow (calls Level 2)
        level1_workflow = MockWorkflow(
            name="Level 1",
            inputs=[{"id": "input_m_int", "name": "M", "type": "int", "range": {"min": 0, "max": 100}}],
            outputs=[{"name": "L1Result"}],
            tree={
                "start": {
                    "id": "start",
                    "type": "start",
                    "children": [
                        {
                            "id": "call_l2",
                            "type": "subprocess",
                            "label": "Call Level 2",
                            "subworkflow_id": "wf_level2",
                            "input_mapping": {"M": "N"},
                            "output_variable": "FromL2",
                            "children": [
                                {
                                    "id": "out",
                                    "type": "output",
                                    "label": "Done",
                                    "output_type": "int",
                                    "output_template": "{FromL2}",
                                    "children": []
                                }
                            ]
                        }
                    ]
                }
            }
        )
        
        workflow_store = MockWorkflowStore({
            "wf_level1": level1_workflow,
            "wf_level2": level2_workflow,
        })
        
        # Parent workflow calls Level 1
        parent_tree = {
            "start": {
                "id": "start",
                "type": "start",
                "children": [
                    {
                        "id": "call_l1",
                        "type": "subprocess",
                        "label": "Call Level 1",
                        "subworkflow_id": "wf_level1",
                        "input_mapping": {"Value": "M"},
                        "output_variable": "FinalResult",
                        "children": [
                            {
                                "id": "out",
                                "type": "output",
                                "label": "Final",
                                "output_type": "int",
                                "output_template": "{FinalResult}",
                                "children": []
                            }
                        ]
                    }
                ]
            }
        }
        
        interpreter = TreeInterpreter(
            tree=parent_tree,
            inputs=[{"id": "input_value_int", "name": "Value", "type": "int", "range": {"min": 0, "max": 100}}],
            outputs=[{"name": "Final"}],
            workflow_id="wf_parent",
            workflow_store=workflow_store,
            user_id="test_user",
        )
        
        result = interpreter.execute({"input_value_int": 10})
        
        assert result.success is True
        # The final result should be 42 (from Level 2)
        assert result.output == "42"  # Template renders as string
        
        # Should have one subflow result from Level 1 (Level 2's result is nested)
        assert len(result.subflow_results) == 1
        assert result.subflow_results[0]["subworkflow_id"] == "wf_level1"


class TestSubflowTreeRebuild:
    """Test subflow execution when stored tree is empty (fallback to nodes/edges)."""
    
    def test_subflow_with_empty_tree_rebuilt_from_nodes_edges(self):
        """Test that subflow execution works when tree is empty but nodes/edges exist.
        
        This simulates workflows saved before tree computation was added to the
        save endpoint. The interpreter should rebuild the tree from nodes/edges.
        """
        # Create a MockWorkflow with empty tree but valid nodes/edges
        class MockWorkflowWithNodesEdges:
            """Mock workflow with empty tree but valid nodes/edges structure."""
            def __init__(self):
                self.name = "Empty Tree Workflow"
                self.tree = {}  # Empty tree - simulates old saved workflow
                self.nodes = [
                    {"id": "start_1", "type": "start", "label": "Start", "x": 0, "y": 0},
                    {"id": "end_1", "type": "end", "label": "Result", "x": 100, "y": 100,
                     "output_type": "string", "output_value": "success"},
                ]
                self.edges = [
                    {"from": "start_1", "to": "end_1", "label": ""},
                ]
                self.inputs = []
                self.outputs = [{"name": "Result", "type": "string"}]
        
        workflow_store = MockWorkflowStore({
            "wf_empty_tree": MockWorkflowWithNodesEdges()
        })
        
        # Parent workflow that calls the subworkflow with empty tree
        parent_tree = {
            "start": {
                "id": "start",
                "type": "start",
                "label": "Start",
                "children": [
                    {
                        "id": "call_sub",
                        "type": "subprocess",
                        "label": "Call Empty Tree Workflow",
                        "subworkflow_id": "wf_empty_tree",
                        "input_mapping": {},
                        "output_variable": "SubResult",
                        "children": [
                            {
                                "id": "out",
                                "type": "end",
                                "label": "Done",
                                "output_type": "string",
                                "output_template": "Got: {SubResult}",
                                "children": []
                            }
                        ]
                    }
                ]
            }
        }
        
        interpreter = TreeInterpreter(
            tree=parent_tree,
            inputs=[],
            outputs=[{"name": "Done", "type": "string"}],
            workflow_id="wf_parent",
            workflow_store=workflow_store,
            user_id="test_user",
        )
        
        result = interpreter.execute({})
        
        # Should succeed because interpreter rebuilds tree from nodes/edges
        assert result.success is True
        assert result.output is not None
        assert "success" in str(result.output).lower() or str(result.output) == "Got: success"
    
    def test_subflow_with_cyclic_nodes_and_no_start_fails_gracefully(self):
        """Test that subflow with invalid structure (cycle, no start) gives a helpful error."""
        class MockWorkflowCyclic:
            """Mock workflow with cyclic nodes - no valid start can be determined."""
            def __init__(self):
                self.name = "Cyclic Workflow"
                self.tree = {}
                # Create a cycle: A -> B -> A (both have incoming edges, so no start)
                self.nodes = [
                    {"id": "node_a", "type": "process", "label": "Node A", "x": 0, "y": 0},
                    {"id": "node_b", "type": "process", "label": "Node B", "x": 100, "y": 100},
                ]
                self.edges = [
                    {"from": "node_a", "to": "node_b", "label": ""},
                    {"from": "node_b", "to": "node_a", "label": ""},  # Creates cycle
                ]
                self.inputs = []
                self.outputs = []
        
        workflow_store = MockWorkflowStore({
            "wf_cyclic": MockWorkflowCyclic()
        })
        
        parent_tree = {
            "start": {
                "id": "start",
                "type": "start",
                "label": "Start",
                "children": [
                    {
                        "id": "call_sub",
                        "type": "subprocess",
                        "label": "Call Cyclic Workflow",
                        "subworkflow_id": "wf_cyclic",
                        "input_mapping": {},
                        "output_variable": "SubResult",
                        "children": [
                            {
                                "id": "out",
                                "type": "end",
                                "label": "Done",
                                "children": []
                            }
                        ]
                    }
                ]
            }
        }
        
        interpreter = TreeInterpreter(
            tree=parent_tree,
            inputs=[],
            outputs=[{"name": "Done"}],
            workflow_id="wf_parent",
            workflow_store=workflow_store,
            user_id="test_user",
        )
        
        # Should return a failed result with a helpful error message
        result = interpreter.execute({})
        
        assert result.success is False
        assert result.error is not None
        assert "no start node" in result.error.lower()
        assert "Cyclic Workflow" in result.error
