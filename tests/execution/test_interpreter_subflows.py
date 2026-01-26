"""Tests for workflow subprocess (subflow) execution.

Tests cover:
1. Simple subflow execution
2. Input mapping from parent to subflow
3. Output injection as new input variable
4. Using subflow output in subsequent decisions
5. Cycle detection (direct and indirect)
6. Error propagation from subflows
7. Nested subflows (subflow calling another subflow)
8. Multiple sequential subflows
"""

import pytest
from unittest.mock import Mock, MagicMock
from src.backend.execution.interpreter import (
    TreeInterpreter,
    InterpreterError,
    SubflowCycleError,
    ExecutionResult,
)


# =============================================================================
# MOCK WORKFLOW STORE
# =============================================================================

class MockWorkflowStore:
    """Mock WorkflowStore for testing subflow execution."""
    
    def __init__(self, workflows: dict):
        """
        Args:
            workflows: Dict mapping workflow_id to workflow objects
        """
        self.workflows = workflows
    
    def get_workflow(self, workflow_id: str, user_id: str):
        """Return workflow by ID, or None if not found."""
        return self.workflows.get(workflow_id)


class MockWorkflow:
    """Mock workflow object with required attributes."""
    
    def __init__(self, name: str, tree: dict, inputs: list, outputs: list):
        self.name = name
        self.tree = tree
        self.inputs = inputs
        self.outputs = outputs


# =============================================================================
# FIXTURE WORKFLOWS
# =============================================================================

# Subworkflow: Credit Score Calculator
# Takes Income and Age, returns a credit score (int)
CREDIT_SCORE_WORKFLOW = MockWorkflow(
    name="Credit Score Calculator",
    inputs=[
        {"id": "input_income_int", "name": "Income", "type": "int", "range": {"min": 0, "max": 1000000}},
        {"id": "input_age_int", "name": "Age", "type": "int", "range": {"min": 18, "max": 120}},
    ],
    outputs=[{"name": "CreditScore"}],
    tree={
        "start": {
            "id": "start",
            "type": "start",
            "label": "Start",
            "children": [
                {
                    "id": "income_check",
                    "type": "decision",
                    "label": "Income >= 50000",
                    "children": [
                        {
                            "id": "age_check_high",
                            "type": "decision",
                            "label": "Age >= 30",
                            "edge_label": "Yes",
                            "children": [
                                {
                                    "id": "out_excellent",
                                    "type": "output",
                                    "label": "800",
                                    "output_type": "int",
                                    "output_value": 800,
                                    "edge_label": "Yes",
                                    "children": []
                                },
                                {
                                    "id": "out_good",
                                    "type": "output",
                                    "label": "700",
                                    "output_type": "int",
                                    "output_value": 700,
                                    "edge_label": "No",
                                    "children": []
                                }
                            ]
                        },
                        {
                            "id": "out_fair",
                            "type": "output",
                            "label": "600",
                            "output_type": "int",
                            "output_value": 600,
                            "edge_label": "No",
                            "children": []
                        }
                    ]
                }
            ]
        }
    }
)

# Parent workflow: Loan Approval
# Calls Credit Score subworkflow, then uses output in decision
LOAN_APPROVAL_WORKFLOW = {
    "inputs": [
        {"id": "input_applicant_income_int", "name": "ApplicantIncome", "type": "int", "range": {"min": 0, "max": 1000000}},
        {"id": "input_applicant_age_int", "name": "ApplicantAge", "type": "int", "range": {"min": 18, "max": 120}},
        {"id": "input_loan_amount_int", "name": "LoanAmount", "type": "int", "range": {"min": 1000, "max": 1000000}},
    ],
    "outputs": [
        {"name": "Approved"},
        {"name": "Denied"},
        {"name": "Manual Review"},
    ],
    "tree": {
        "start": {
            "id": "start",
            "type": "start",
            "label": "Start",
            "children": [
                {
                    "id": "credit_check",
                    "type": "subprocess",
                    "label": "Calculate Credit Score",
                    "subworkflow_id": "wf_credit_score",
                    "input_mapping": {
                        "ApplicantIncome": "Income",
                        "ApplicantAge": "Age"
                    },
                    "output_variable": "CreditScore",
                    "children": [
                        {
                            "id": "score_check",
                            "type": "decision",
                            "label": "CreditScore >= 700",
                            "children": [
                                {
                                    "id": "amount_check",
                                    "type": "decision",
                                    "label": "LoanAmount <= 100000",
                                    "edge_label": "Yes",
                                    "children": [
                                        {
                                            "id": "out_approved",
                                            "type": "output",
                                            "label": "Approved",
                                            "edge_label": "Yes",
                                            "children": []
                                        },
                                        {
                                            "id": "out_review",
                                            "type": "output",
                                            "label": "Manual Review",
                                            "edge_label": "No",
                                            "children": []
                                        }
                                    ]
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
}

# Workflow that calls itself (direct cycle)
SELF_CALLING_WORKFLOW = MockWorkflow(
    name="Self Caller",
    inputs=[{"id": "input_x_int", "name": "X", "type": "int", "range": {"min": 0, "max": 100}}],
    outputs=[{"name": "Result"}],
    tree={
        "start": {
            "id": "start",
            "type": "start",
            "label": "Start",
            "children": [
                {
                    "id": "recurse",
                    "type": "subprocess",
                    "label": "Call Self",
                    "subworkflow_id": "wf_self_caller",
                    "input_mapping": {"X": "X"},
                    "output_variable": "Result",
                    "children": [
                        {"id": "out", "type": "output", "label": "Done", "children": []}
                    ]
                }
            ]
        }
    }
)

# Workflow A calls Workflow B, which calls Workflow A (indirect cycle)
WORKFLOW_A = MockWorkflow(
    name="Workflow A",
    inputs=[{"id": "input_val_int", "name": "Val", "type": "int", "range": {"min": 0, "max": 100}}],
    outputs=[{"name": "ResultA"}],
    tree={
        "start": {
            "id": "start",
            "type": "start",
            "label": "Start",
            "children": [
                {
                    "id": "call_b",
                    "type": "subprocess",
                    "label": "Call B",
                    "subworkflow_id": "wf_b",
                    "input_mapping": {"Val": "Input"},
                    "output_variable": "FromB",
                    "children": [
                        {"id": "out_a", "type": "output", "label": "ResultA", "children": []}
                    ]
                }
            ]
        }
    }
)

WORKFLOW_B = MockWorkflow(
    name="Workflow B",
    inputs=[{"id": "input_input_int", "name": "Input", "type": "int", "range": {"min": 0, "max": 100}}],
    outputs=[{"name": "ResultB"}],
    tree={
        "start": {
            "id": "start",
            "type": "start",
            "label": "Start",
            "children": [
                {
                    "id": "call_a",
                    "type": "subprocess",
                    "label": "Call A",
                    "subworkflow_id": "wf_a",
                    "input_mapping": {"Input": "Val"},
                    "output_variable": "FromA",
                    "children": [
                        {"id": "out_b", "type": "output", "label": "ResultB", "children": []}
                    ]
                }
            ]
        }
    }
)

# Simple workflow for nesting tests (no subflows)
SIMPLE_DOUBLER = MockWorkflow(
    name="Doubler",
    inputs=[{"id": "input_n_int", "name": "N", "type": "int", "range": {"min": 0, "max": 1000}}],
    outputs=[{"name": "Doubled"}],
    tree={
        "start": {
            "id": "start",
            "type": "start",
            "label": "Start",
            "children": [
                {
                    "id": "out",
                    "type": "output",
                    "label": "Doubled",
                    "output_type": "int",
                    "output_template": "{N}",  # Just returns the input (mock doubling)
                    "children": []
                }
            ]
        }
    }
)


# =============================================================================
# TEST CLASSES
# =============================================================================

class TestSimpleSubflowExecution:
    """Test basic subflow execution."""
    
    def test_subflow_executes_and_returns_output(self):
        """Test that subflow executes and its output is available."""
        workflow_store = MockWorkflowStore({
            "wf_credit_score": CREDIT_SCORE_WORKFLOW
        })
        
        interpreter = TreeInterpreter(
            tree=LOAN_APPROVAL_WORKFLOW["tree"],
            inputs=LOAN_APPROVAL_WORKFLOW["inputs"],
            outputs=LOAN_APPROVAL_WORKFLOW["outputs"],
            workflow_id="wf_loan_approval",
            workflow_store=workflow_store,
            user_id="test_user",
        )
        
        # High income, age >= 30 -> Credit Score 800, small loan -> Approved
        result = interpreter.execute({
            "input_applicant_income_int": 60000,
            "input_applicant_age_int": 35,
            "input_loan_amount_int": 50000
        })
        
        assert result.success is True
        assert result.output == "Approved"
        assert "credit_check" in result.path
        assert "score_check" in result.path
    
    def test_subflow_output_used_in_subsequent_decision(self):
        """Test that subflow output becomes available as input for later decisions."""
        workflow_store = MockWorkflowStore({
            "wf_credit_score": CREDIT_SCORE_WORKFLOW
        })
        
        interpreter = TreeInterpreter(
            tree=LOAN_APPROVAL_WORKFLOW["tree"],
            inputs=LOAN_APPROVAL_WORKFLOW["inputs"],
            outputs=LOAN_APPROVAL_WORKFLOW["outputs"],
            workflow_id="wf_loan_approval",
            workflow_store=workflow_store,
            user_id="test_user",
        )
        
        # Low income -> Credit Score 600 -> Denied
        result = interpreter.execute({
            "input_applicant_income_int": 30000,
            "input_applicant_age_int": 25,
            "input_loan_amount_int": 50000
        })
        
        assert result.success is True
        assert result.output == "Denied"
    
    def test_subflow_results_tracked(self):
        """Test that subflow execution results are tracked in result.subflow_results."""
        workflow_store = MockWorkflowStore({
            "wf_credit_score": CREDIT_SCORE_WORKFLOW
        })
        
        interpreter = TreeInterpreter(
            tree=LOAN_APPROVAL_WORKFLOW["tree"],
            inputs=LOAN_APPROVAL_WORKFLOW["inputs"],
            outputs=LOAN_APPROVAL_WORKFLOW["outputs"],
            workflow_id="wf_loan_approval",
            workflow_store=workflow_store,
            user_id="test_user",
        )
        
        result = interpreter.execute({
            "input_applicant_income_int": 60000,
            "input_applicant_age_int": 35,
            "input_loan_amount_int": 50000
        })
        
        assert len(result.subflow_results) == 1
        subflow_result = result.subflow_results[0]
        assert subflow_result["subworkflow_id"] == "wf_credit_score"
        assert subflow_result["subworkflow_name"] == "Credit Score Calculator"
        assert subflow_result["output_variable"] == "CreditScore"
        assert subflow_result["result"]["success"] is True
        assert subflow_result["result"]["output"] == 800


class TestSubflowInputMapping:
    """Test input mapping from parent to subflow."""
    
    def test_input_mapping_translates_names_correctly(self):
        """Test that parent inputs are correctly mapped to subworkflow inputs."""
        workflow_store = MockWorkflowStore({
            "wf_credit_score": CREDIT_SCORE_WORKFLOW
        })
        
        interpreter = TreeInterpreter(
            tree=LOAN_APPROVAL_WORKFLOW["tree"],
            inputs=LOAN_APPROVAL_WORKFLOW["inputs"],
            outputs=LOAN_APPROVAL_WORKFLOW["outputs"],
            workflow_id="wf_loan_approval",
            workflow_store=workflow_store,
            user_id="test_user",
        )
        
        result = interpreter.execute({
            "input_applicant_income_int": 60000,
            "input_applicant_age_int": 35,
            "input_loan_amount_int": 50000
        })
        
        # Check mapped inputs in subflow result
        subflow_result = result.subflow_results[0]
        assert "input_income_int" in subflow_result["sub_inputs"]
        assert "input_age_int" in subflow_result["sub_inputs"]
        assert subflow_result["sub_inputs"]["input_income_int"] == 60000
        assert subflow_result["sub_inputs"]["input_age_int"] == 35
    
    def test_missing_parent_input_in_mapping_fails(self):
        """Test error when input_mapping references non-existent parent input."""
        # Workflow with invalid input mapping
        bad_workflow = {
            "inputs": [
                {"id": "input_x_int", "name": "X", "type": "int", "range": {"min": 0, "max": 100}}
            ],
            "outputs": [{"name": "Result"}],
            "tree": {
                "start": {
                    "id": "start",
                    "type": "start",
                    "children": [
                        {
                            "id": "sub",
                            "type": "subprocess",
                            "label": "Call Sub",
                            "subworkflow_id": "wf_credit_score",
                            "input_mapping": {"NonExistent": "Income"},  # Bad mapping
                            "output_variable": "Result",
                            "children": [
                                {"id": "out", "type": "output", "label": "Done", "children": []}
                            ]
                        }
                    ]
                }
            }
        }
        
        workflow_store = MockWorkflowStore({"wf_credit_score": CREDIT_SCORE_WORKFLOW})
        
        interpreter = TreeInterpreter(
            tree=bad_workflow["tree"],
            inputs=bad_workflow["inputs"],
            outputs=bad_workflow["outputs"],
            workflow_store=workflow_store,
            user_id="test_user",
        )
        
        result = interpreter.execute({"input_x_int": 10})
        
        assert result.success is False
        assert "non-existent parent input" in result.error


class TestCycleDetection:
    """Test cycle detection prevents infinite recursion."""
    
    def test_direct_cycle_detected(self):
        """Test that workflow calling itself is detected."""
        workflow_store = MockWorkflowStore({
            "wf_self_caller": SELF_CALLING_WORKFLOW
        })
        
        interpreter = TreeInterpreter(
            tree=SELF_CALLING_WORKFLOW.tree,
            inputs=SELF_CALLING_WORKFLOW.inputs,
            outputs=SELF_CALLING_WORKFLOW.outputs,
            workflow_id="wf_self_caller",
            workflow_store=workflow_store,
            user_id="test_user",
        )
        
        result = interpreter.execute({"input_x_int": 10})
        
        assert result.success is False
        assert "Circular subflow detected" in result.error
        assert "wf_self_caller" in result.error
    
    def test_indirect_cycle_detected(self):
        """Test that A->B->A cycle is detected."""
        workflow_store = MockWorkflowStore({
            "wf_a": WORKFLOW_A,
            "wf_b": WORKFLOW_B,
        })
        
        interpreter = TreeInterpreter(
            tree=WORKFLOW_A.tree,
            inputs=WORKFLOW_A.inputs,
            outputs=WORKFLOW_A.outputs,
            workflow_id="wf_a",
            workflow_store=workflow_store,
            user_id="test_user",
        )
        
        result = interpreter.execute({"input_val_int": 10})
        
        assert result.success is False
        assert "Circular subflow detected" in result.error


class TestSubflowErrorPropagation:
    """Test that subflow errors propagate to parent."""
    
    def test_subflow_error_fails_parent(self):
        """Test that if subflow fails, parent workflow fails."""
        # Subworkflow that will fail with bad input
        failing_subworkflow = MockWorkflow(
            name="Failing Workflow",
            inputs=[{"id": "input_val_int", "name": "Val", "type": "int", "range": {"min": 0, "max": 10}}],
            outputs=[{"name": "Result"}],
            tree={
                "start": {
                    "id": "start",
                    "type": "start",
                    "children": [
                        {"id": "out", "type": "output", "label": "Done", "children": []}
                    ]
                }
            }
        )
        
        parent_workflow = {
            "inputs": [
                {"id": "input_x_int", "name": "X", "type": "int", "range": {"min": 0, "max": 1000}}
            ],
            "outputs": [{"name": "Result"}],
            "tree": {
                "start": {
                    "id": "start",
                    "type": "start",
                    "children": [
                        {
                            "id": "sub",
                            "type": "subprocess",
                            "label": "Call Sub",
                            "subworkflow_id": "wf_fail",
                            "input_mapping": {"X": "Val"},  # Will pass 100 which exceeds max 10
                            "output_variable": "Result",
                            "children": [
                                {"id": "out", "type": "output", "label": "Done", "children": []}
                            ]
                        }
                    ]
                }
            }
        }
        
        workflow_store = MockWorkflowStore({"wf_fail": failing_subworkflow})
        
        interpreter = TreeInterpreter(
            tree=parent_workflow["tree"],
            inputs=parent_workflow["inputs"],
            outputs=parent_workflow["outputs"],
            workflow_store=workflow_store,
            user_id="test_user",
        )
        
        # Pass value 100 which exceeds subworkflow's max of 10
        result = interpreter.execute({"input_x_int": 100})
        
        assert result.success is False
        assert "failed" in result.error.lower() or "exceeds maximum" in result.error.lower()


class TestMissingSubflowConfiguration:
    """Test error handling for missing subprocess configuration."""
    
    def test_missing_subworkflow_id_fails(self):
        """Test error when subprocess node has no subworkflow_id."""
        bad_workflow = {
            "inputs": [{"id": "input_x_int", "name": "X", "type": "int", "range": {"min": 0, "max": 100}}],
            "outputs": [{"name": "Result"}],
            "tree": {
                "start": {
                    "id": "start",
                    "type": "start",
                    "children": [
                        {
                            "id": "sub",
                            "type": "subprocess",
                            "label": "Missing Subworkflow",
                            # No subworkflow_id!
                            "input_mapping": {},
                            "output_variable": "Result",
                            "children": [
                                {"id": "out", "type": "output", "label": "Done", "children": []}
                            ]
                        }
                    ]
                }
            }
        }
        
        interpreter = TreeInterpreter(
            tree=bad_workflow["tree"],
            inputs=bad_workflow["inputs"],
            outputs=bad_workflow["outputs"],
            workflow_store=MockWorkflowStore({}),
            user_id="test_user",
        )
        
        result = interpreter.execute({"input_x_int": 10})
        
        assert result.success is False
        assert "missing subworkflow_id" in result.error.lower()
    
    def test_missing_output_variable_fails(self):
        """Test error when subprocess node has no output_variable."""
        bad_workflow = {
            "inputs": [{"id": "input_x_int", "name": "X", "type": "int", "range": {"min": 0, "max": 100}}],
            "outputs": [{"name": "Result"}],
            "tree": {
                "start": {
                    "id": "start",
                    "type": "start",
                    "children": [
                        {
                            "id": "sub",
                            "type": "subprocess",
                            "label": "Missing Output Var",
                            "subworkflow_id": "wf_something",
                            "input_mapping": {},
                            # No output_variable!
                            "children": [
                                {"id": "out", "type": "output", "label": "Done", "children": []}
                            ]
                        }
                    ]
                }
            }
        }
        
        interpreter = TreeInterpreter(
            tree=bad_workflow["tree"],
            inputs=bad_workflow["inputs"],
            outputs=bad_workflow["outputs"],
            workflow_store=MockWorkflowStore({}),
            user_id="test_user",
        )
        
        result = interpreter.execute({"input_x_int": 10})
        
        assert result.success is False
        assert "missing output_variable" in result.error.lower()
    
    def test_subworkflow_not_found_fails(self):
        """Test error when referenced subworkflow doesn't exist."""
        workflow = {
            "inputs": [{"id": "input_x_int", "name": "X", "type": "int", "range": {"min": 0, "max": 100}}],
            "outputs": [{"name": "Result"}],
            "tree": {
                "start": {
                    "id": "start",
                    "type": "start",
                    "children": [
                        {
                            "id": "sub",
                            "type": "subprocess",
                            "label": "Call Missing",
                            "subworkflow_id": "wf_does_not_exist",
                            "input_mapping": {},
                            "output_variable": "Result",
                            "children": [
                                {"id": "out", "type": "output", "label": "Done", "children": []}
                            ]
                        }
                    ]
                }
            }
        }
        
        # Empty workflow store
        interpreter = TreeInterpreter(
            tree=workflow["tree"],
            inputs=workflow["inputs"],
            outputs=workflow["outputs"],
            workflow_store=MockWorkflowStore({}),
            user_id="test_user",
        )
        
        result = interpreter.execute({"input_x_int": 10})
        
        assert result.success is False
        assert "not found" in result.error.lower()
    
    def test_missing_workflow_store_fails(self):
        """Test error when workflow_store is not provided."""
        workflow = {
            "inputs": [{"id": "input_x_int", "name": "X", "type": "int", "range": {"min": 0, "max": 100}}],
            "outputs": [{"name": "Result"}],
            "tree": {
                "start": {
                    "id": "start",
                    "type": "start",
                    "children": [
                        {
                            "id": "sub",
                            "type": "subprocess",
                            "label": "Call Something",
                            "subworkflow_id": "wf_something",
                            "input_mapping": {},
                            "output_variable": "Result",
                            "children": [
                                {"id": "out", "type": "output", "label": "Done", "children": []}
                            ]
                        }
                    ]
                }
            }
        }
        
        # No workflow_store
        interpreter = TreeInterpreter(
            tree=workflow["tree"],
            inputs=workflow["inputs"],
            outputs=workflow["outputs"],
            # workflow_store=None (default)
            user_id="test_user",
        )
        
        result = interpreter.execute({"input_x_int": 10})
        
        assert result.success is False
        assert "workflow_store not available" in result.error


class TestOutputVariableInjection:
    """Test that subflow output is properly injected as a new input variable."""
    
    def test_output_variable_added_to_context(self):
        """Test that output variable is added to context after subflow execution."""
        workflow_store = MockWorkflowStore({
            "wf_credit_score": CREDIT_SCORE_WORKFLOW
        })
        
        interpreter = TreeInterpreter(
            tree=LOAN_APPROVAL_WORKFLOW["tree"],
            inputs=LOAN_APPROVAL_WORKFLOW["inputs"],
            outputs=LOAN_APPROVAL_WORKFLOW["outputs"],
            workflow_id="wf_loan_approval",
            workflow_store=workflow_store,
            user_id="test_user",
        )
        
        result = interpreter.execute({
            "input_applicant_income_int": 60000,
            "input_applicant_age_int": 35,
            "input_loan_amount_int": 50000
        })
        
        # The CreditScore should be in context as a dynamically added input
        assert "input_creditscore_int" in result.context
        assert result.context["input_creditscore_int"] == 800
    
    def test_output_variable_used_in_decision(self):
        """Test that injected output variable can be used in subsequent decision."""
        workflow_store = MockWorkflowStore({
            "wf_credit_score": CREDIT_SCORE_WORKFLOW
        })
        
        interpreter = TreeInterpreter(
            tree=LOAN_APPROVAL_WORKFLOW["tree"],
            inputs=LOAN_APPROVAL_WORKFLOW["inputs"],
            outputs=LOAN_APPROVAL_WORKFLOW["outputs"],
            workflow_id="wf_loan_approval",
            workflow_store=workflow_store,
            user_id="test_user",
        )
        
        # Test case where CreditScore affects the outcome
        # High income, young -> Score 700
        result = interpreter.execute({
            "input_applicant_income_int": 60000,
            "input_applicant_age_int": 25,  # Young -> 700 score
            "input_loan_amount_int": 50000
        })
        
        assert result.success is True
        assert result.output == "Approved"  # 700 >= 700, loan <= 100k


class TestSubflowTypeInference:
    """Test type inference for subflow outputs."""
    
    def test_int_output_inferred_correctly(self):
        """Test that integer output creates int type input."""
        workflow_store = MockWorkflowStore({
            "wf_credit_score": CREDIT_SCORE_WORKFLOW
        })
        
        interpreter = TreeInterpreter(
            tree=LOAN_APPROVAL_WORKFLOW["tree"],
            inputs=LOAN_APPROVAL_WORKFLOW["inputs"],
            outputs=LOAN_APPROVAL_WORKFLOW["outputs"],
            workflow_id="wf_loan_approval",
            workflow_store=workflow_store,
            user_id="test_user",
        )
        
        result = interpreter.execute({
            "input_applicant_income_int": 60000,
            "input_applicant_age_int": 35,
            "input_loan_amount_int": 50000
        })
        
        # Check that CreditScore was registered with int type
        assert "input_creditscore_int" in interpreter.inputs_schema
        assert interpreter.inputs_schema["input_creditscore_int"]["type"] == "int"


class TestSubflowWithNoChildren:
    """Test error when subprocess node has no children."""
    
    def test_subprocess_without_children_fails(self):
        """Test that subprocess node must have children to continue flow."""
        workflow = {
            "inputs": [{"id": "input_x_int", "name": "X", "type": "int", "range": {"min": 0, "max": 100}}],
            "outputs": [{"name": "Result"}],
            "tree": {
                "start": {
                    "id": "start",
                    "type": "start",
                    "children": [
                        {
                            "id": "sub",
                            "type": "subprocess",
                            "label": "No Children",
                            "subworkflow_id": "wf_simple",
                            "input_mapping": {"X": "N"},
                            "output_variable": "Result",
                            "children": []  # No children!
                        }
                    ]
                }
            }
        }
        
        workflow_store = MockWorkflowStore({"wf_simple": SIMPLE_DOUBLER})
        
        interpreter = TreeInterpreter(
            tree=workflow["tree"],
            inputs=workflow["inputs"],
            outputs=workflow["outputs"],
            workflow_store=workflow_store,
            user_id="test_user",
        )
        
        result = interpreter.execute({"input_x_int": 10})
        
        assert result.success is False
        assert "no children" in result.error.lower()
