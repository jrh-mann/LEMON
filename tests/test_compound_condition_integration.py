"""Integration tests for compound (AND/OR) conditions — end-to-end.

Tests the full lifecycle:
1. Create a workflow via tools
2. Add boolean/numeric variables
3. Add decision nodes with compound conditions (OR, AND)
4. Execute the workflow with different inputs, verify branch selection
5. Verify get_current_workflow formats compound conditions correctly
6. Verify remove_workflow_variable detects compound references and cascade-deletes
"""

import pytest

from src.backend.tools import CreateWorkflowTool
from src.backend.tools.workflow_edit import (
    AddConnectionTool,
    AddNodeTool,
    GetCurrentWorkflowTool,
)
from src.backend.tools.workflow_input import (
    AddWorkflowVariableTool,
    RemoveWorkflowVariableTool,
)
from src.backend.tools.execute_workflow import ExecuteWorkflowTool
from tests.conftest import make_session_with_workflow


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def tools():
    """All tool instances needed for the integration test."""
    return {
        "create": CreateWorkflowTool(),
        "add_var": AddWorkflowVariableTool(),
        "remove_var": RemoveWorkflowVariableTool(),
        "add_node": AddNodeTool(),
        "add_conn": AddConnectionTool(),
        "get_current": GetCurrentWorkflowTool(),
        "execute": ExecuteWorkflowTool(),
    }


def _create_cvd_workflow(workflow_store, test_user_id, tools):
    """Build a CVD-screening workflow with compound OR condition.

    Structure:
        [Start: Patient] → [Decision: CVD Risk?] → Yes → [End: Screen]
                                                  → No  → [End: Skip]

    Decision condition (OR): cvd_known is_true  OR  cvd_at_risk is_true
    """
    # 1. Create workflow
    session = {"workflow_store": workflow_store, "user_id": test_user_id}
    res = tools["create"].execute(
        {"name": "CVD Screening", "output_type": "string"},
        session_state=session,
    )
    assert res["success"], f"create_workflow failed: {res}"
    wf_id = res["workflow_id"]

    # 2. Add variables
    for var in [
        {"workflow_id": wf_id, "name": "CVD Known", "type": "boolean"},
        {"workflow_id": wf_id, "name": "CVD At Risk", "type": "boolean"},
    ]:
        r = tools["add_var"].execute(var, session_state=session)
        assert r["success"], f"add_variable failed: {r}"

    # Grab variable IDs from the database
    record = workflow_store.get_workflow(wf_id, test_user_id)
    variables = list(record.inputs)
    var_ids = {v["name"]: v["id"] for v in variables}

    # 3. Build nodes (seed directly for speed — tools already tested elsewhere)
    nodes = [
        {"id": "n_start", "type": "start", "label": "Patient", "x": 0, "y": 0},
        {
            "id": "n_decision",
            "type": "decision",
            "label": "CVD Risk?",
            "x": 100,
            "y": 0,
            # Compound OR condition
            "condition": {
                "operator": "or",
                "conditions": [
                    {"input_id": var_ids["CVD Known"], "comparator": "is_true"},
                    {"input_id": var_ids["CVD At Risk"], "comparator": "is_true"},
                ],
            },
        },
        {
            "id": "n_screen",
            "type": "end",
            "label": "Screen",
            "x": 200,
            "y": -50,
            "output_value": "Screen for CVD",
        },
        {
            "id": "n_skip",
            "type": "end",
            "label": "Skip",
            "x": 200,
            "y": 50,
            "output_value": "No screening needed",
        },
    ]
    edges = [
        {"id": "n_start->n_decision", "from": "n_start", "to": "n_decision", "label": ""},
        {"id": "n_decision->n_screen", "from": "n_decision", "to": "n_screen", "label": "true"},
        {"id": "n_decision->n_skip", "from": "n_decision", "to": "n_skip", "label": "false"},
    ]
    workflow_store.update_workflow(
        workflow_id=wf_id,
        user_id=test_user_id,
        nodes=nodes,
        edges=edges,
        inputs=variables,
    )

    return wf_id, session, var_ids, variables


def _create_diabetes_workflow(workflow_store, test_user_id, tools):
    """Build a diabetes-check workflow with compound AND condition.

    Structure:
        [Start: Patient] → [Decision: Diabetes?] → Yes → [End: Diagnose]
                                                  → No  → [End: Clear]

    Decision condition (AND): symptoms_present is_true  AND  a1c > 58
    """
    session = {"workflow_store": workflow_store, "user_id": test_user_id}
    res = tools["create"].execute(
        {"name": "Diabetes Check", "output_type": "string"},
        session_state=session,
    )
    assert res["success"], f"create_workflow failed: {res}"
    wf_id = res["workflow_id"]

    for var in [
        {"workflow_id": wf_id, "name": "Symptoms Present", "type": "boolean"},
        {"workflow_id": wf_id, "name": "A1c", "type": "number"},
    ]:
        r = tools["add_var"].execute(var, session_state=session)
        assert r["success"], f"add_variable failed: {r}"

    record = workflow_store.get_workflow(wf_id, test_user_id)
    variables = list(record.inputs)
    var_ids = {v["name"]: v["id"] for v in variables}

    nodes = [
        {"id": "n_start", "type": "start", "label": "Patient", "x": 0, "y": 0},
        {
            "id": "n_decision",
            "type": "decision",
            "label": "Diabetes?",
            "x": 100,
            "y": 0,
            # Compound AND condition
            "condition": {
                "operator": "and",
                "conditions": [
                    {"input_id": var_ids["Symptoms Present"], "comparator": "is_true"},
                    {"input_id": var_ids["A1c"], "comparator": "gt", "value": 58},
                ],
            },
        },
        {
            "id": "n_diagnose",
            "type": "end",
            "label": "Diagnose",
            "x": 200,
            "y": -50,
            "output_value": "Diabetes diagnosed",
        },
        {
            "id": "n_clear",
            "type": "end",
            "label": "Clear",
            "x": 200,
            "y": 50,
            "output_value": "No diabetes",
        },
    ]
    edges = [
        {"id": "n_start->n_decision", "from": "n_start", "to": "n_decision", "label": ""},
        {"id": "n_decision->n_diagnose", "from": "n_decision", "to": "n_diagnose", "label": "true"},
        {"id": "n_decision->n_clear", "from": "n_decision", "to": "n_clear", "label": "false"},
    ]
    workflow_store.update_workflow(
        workflow_id=wf_id,
        user_id=test_user_id,
        nodes=nodes,
        edges=edges,
        inputs=variables,
    )

    return wf_id, session, var_ids, variables


# =============================================================================
# TEST: OR compound execution
# =============================================================================


class TestCompoundOrExecution:
    """Execute a workflow whose decision uses OR compound condition."""

    def test_or_both_true(self, workflow_store, test_user_id, tools):
        """OR: both conditions true → Yes branch."""
        wf_id, session, var_ids, _ = _create_cvd_workflow(
            workflow_store, test_user_id, tools
        )
        result = tools["execute"].execute(
            {
                "workflow_id": wf_id,
                "input_values": {"CVD Known": True, "CVD At Risk": True},
            },
            session_state=session,
        )
        assert result["success"], f"execution failed: {result}"
        assert result["output"] == "Screen for CVD"

    def test_or_first_true(self, workflow_store, test_user_id, tools):
        """OR: first condition true, second false → Yes branch."""
        wf_id, session, var_ids, _ = _create_cvd_workflow(
            workflow_store, test_user_id, tools
        )
        result = tools["execute"].execute(
            {
                "workflow_id": wf_id,
                "input_values": {"CVD Known": True, "CVD At Risk": False},
            },
            session_state=session,
        )
        assert result["success"], f"execution failed: {result}"
        assert result["output"] == "Screen for CVD"

    def test_or_second_true(self, workflow_store, test_user_id, tools):
        """OR: first false, second true → Yes branch."""
        wf_id, session, var_ids, _ = _create_cvd_workflow(
            workflow_store, test_user_id, tools
        )
        result = tools["execute"].execute(
            {
                "workflow_id": wf_id,
                "input_values": {"CVD Known": False, "CVD At Risk": True},
            },
            session_state=session,
        )
        assert result["success"], f"execution failed: {result}"
        assert result["output"] == "Screen for CVD"

    def test_or_both_false(self, workflow_store, test_user_id, tools):
        """OR: both false → No branch."""
        wf_id, session, var_ids, _ = _create_cvd_workflow(
            workflow_store, test_user_id, tools
        )
        result = tools["execute"].execute(
            {
                "workflow_id": wf_id,
                "input_values": {"CVD Known": False, "CVD At Risk": False},
            },
            session_state=session,
        )
        assert result["success"], f"execution failed: {result}"
        assert result["output"] == "No screening needed"


# =============================================================================
# TEST: AND compound execution
# =============================================================================


class TestCompoundAndExecution:
    """Execute a workflow whose decision uses AND compound condition."""

    def test_and_both_true(self, workflow_store, test_user_id, tools):
        """AND: both conditions true → Yes branch."""
        wf_id, session, var_ids, _ = _create_diabetes_workflow(
            workflow_store, test_user_id, tools
        )
        result = tools["execute"].execute(
            {
                "workflow_id": wf_id,
                "input_values": {"Symptoms Present": True, "A1c": 65},
            },
            session_state=session,
        )
        assert result["success"], f"execution failed: {result}"
        assert result["output"] == "Diabetes diagnosed"

    def test_and_first_true_second_false(self, workflow_store, test_user_id, tools):
        """AND: symptoms true but A1c low → No branch."""
        wf_id, session, var_ids, _ = _create_diabetes_workflow(
            workflow_store, test_user_id, tools
        )
        result = tools["execute"].execute(
            {
                "workflow_id": wf_id,
                "input_values": {"Symptoms Present": True, "A1c": 50},
            },
            session_state=session,
        )
        assert result["success"], f"execution failed: {result}"
        assert result["output"] == "No diabetes"

    def test_and_first_false_second_true(self, workflow_store, test_user_id, tools):
        """AND: no symptoms but A1c high → No branch."""
        wf_id, session, var_ids, _ = _create_diabetes_workflow(
            workflow_store, test_user_id, tools
        )
        result = tools["execute"].execute(
            {
                "workflow_id": wf_id,
                "input_values": {"Symptoms Present": False, "A1c": 65},
            },
            session_state=session,
        )
        assert result["success"], f"execution failed: {result}"
        assert result["output"] == "No diabetes"

    def test_and_both_false(self, workflow_store, test_user_id, tools):
        """AND: both false → No branch."""
        wf_id, session, var_ids, _ = _create_diabetes_workflow(
            workflow_store, test_user_id, tools
        )
        result = tools["execute"].execute(
            {
                "workflow_id": wf_id,
                "input_values": {"Symptoms Present": False, "A1c": 50},
            },
            session_state=session,
        )
        assert result["success"], f"execution failed: {result}"
        assert result["output"] == "No diabetes"

    def test_and_boundary_value(self, workflow_store, test_user_id, tools):
        """AND: A1c == 58 (not > 58) → No branch (gt is strict)."""
        wf_id, session, var_ids, _ = _create_diabetes_workflow(
            workflow_store, test_user_id, tools
        )
        result = tools["execute"].execute(
            {
                "workflow_id": wf_id,
                "input_values": {"Symptoms Present": True, "A1c": 58},
            },
            session_state=session,
        )
        assert result["success"], f"execution failed: {result}"
        assert result["output"] == "No diabetes"


# =============================================================================
# TEST: get_current_workflow formatting
# =============================================================================


class TestGetCurrentFormatsCompound:
    """Verify get_current_workflow returns human-readable compound condition text."""

    def test_or_condition_formatted(self, workflow_store, test_user_id, tools):
        """OR condition should appear as 'X is_true OR Y is_true' in summary."""
        wf_id, session, var_ids, _ = _create_cvd_workflow(
            workflow_store, test_user_id, tools
        )
        result = tools["get_current"].execute(
            {"workflow_id": wf_id},
            session_state=session,
        )
        assert result["success"], f"get_current failed: {result}"

        # The node descriptions should contain the compound condition text
        node_descs = result["summary"]["node_descriptions"]
        assert "OR" in node_descs, (
            f"Expected 'OR' in node descriptions, got: {node_descs}"
        )

    def test_and_condition_formatted(self, workflow_store, test_user_id, tools):
        """AND condition should appear as 'X is_true AND Y > 58' in summary."""
        wf_id, session, var_ids, _ = _create_diabetes_workflow(
            workflow_store, test_user_id, tools
        )
        result = tools["get_current"].execute(
            {"workflow_id": wf_id},
            session_state=session,
        )
        assert result["success"], f"get_current failed: {result}"

        node_descs = result["summary"]["node_descriptions"]
        assert "AND" in node_descs, (
            f"Expected 'AND' in node descriptions, got: {node_descs}"
        )


# =============================================================================
# TEST: remove_workflow_variable with compound references
# =============================================================================


class TestRemoveVariableCompoundRefs:
    """Verify remove_workflow_variable detects and cascade-deletes compound references."""

    def test_remove_blocked_by_compound_reference(
        self, workflow_store, test_user_id, tools
    ):
        """Removing a variable referenced in a compound condition should fail without force."""
        wf_id, session, var_ids, _ = _create_cvd_workflow(
            workflow_store, test_user_id, tools
        )
        result = tools["remove_var"].execute(
            {"workflow_id": wf_id, "name": "CVD Known"},
            session_state=session,
        )
        assert result["success"] is False
        assert "referenced" in result["error"].lower() or "referencing" in result["error"].lower()

    def test_force_remove_clears_entire_compound_condition(
        self, workflow_store, test_user_id, tools
    ):
        """Force-removing a variable clears the entire compound condition from the node."""
        wf_id, session, var_ids, _ = _create_cvd_workflow(
            workflow_store, test_user_id, tools
        )
        result = tools["remove_var"].execute(
            {"workflow_id": wf_id, "name": "CVD Known", "force": True},
            session_state=session,
        )
        assert result["success"], f"force remove failed: {result}"
        assert result["affected_nodes"] == 1

        # Verify the decision node no longer has a condition
        record = workflow_store.get_workflow(wf_id, test_user_id)
        decision_node = next(
            n for n in record.nodes if n["id"] == "n_decision"
        )
        assert "condition" not in decision_node, (
            f"Expected condition to be cleared, got: {decision_node}"
        )


# =============================================================================
# TEST: add_node tool validates compound conditions
# =============================================================================


class TestAddNodeCompoundValidation:
    """Verify add_node tool validates compound conditions properly."""

    def test_add_node_with_valid_compound_condition(
        self, workflow_store, test_user_id, tools
    ):
        """Adding a decision node with a valid compound condition should succeed."""
        # Create workflow with variables
        session = {"workflow_store": workflow_store, "user_id": test_user_id}
        res = tools["create"].execute(
            {"name": "Test Validation", "output_type": "string"},
            session_state=session,
        )
        wf_id = res["workflow_id"]

        # Add two boolean variables
        for name in ["Flag A", "Flag B"]:
            tools["add_var"].execute(
                {"workflow_id": wf_id, "name": name, "type": "boolean"},
                session_state=session,
            )

        # Fetch variable IDs
        record = workflow_store.get_workflow(wf_id, test_user_id)
        variables = list(record.inputs)
        var_ids = {v["name"]: v["id"] for v in variables}

        # Inject variables into session for add_node validation
        session["workflow_analysis"] = {"variables": variables}

        result = tools["add_node"].execute(
            {
                "workflow_id": wf_id,
                "type": "decision",
                "label": "Check Both?",
                "condition": {
                    "operator": "and",
                    "conditions": [
                        {"input_id": var_ids["Flag A"], "comparator": "is_true"},
                        {"input_id": var_ids["Flag B"], "comparator": "is_true"},
                    ],
                },
            },
            session_state=session,
        )
        assert result["success"], f"add_node with compound condition failed: {result}"
        assert result["node"]["condition"]["operator"] == "and"

    def test_add_node_rejects_nested_compound(
        self, workflow_store, test_user_id, tools
    ):
        """add_node should reject nested compound conditions."""
        session = {"workflow_store": workflow_store, "user_id": test_user_id}
        res = tools["create"].execute(
            {"name": "Test Nested", "output_type": "string"},
            session_state=session,
        )
        wf_id = res["workflow_id"]

        tools["add_var"].execute(
            {"workflow_id": wf_id, "name": "X", "type": "boolean"},
            session_state=session,
        )

        record = workflow_store.get_workflow(wf_id, test_user_id)
        variables = list(record.inputs)
        session["workflow_analysis"] = {"variables": variables}
        var_id = variables[0]["id"]

        result = tools["add_node"].execute(
            {
                "workflow_id": wf_id,
                "type": "decision",
                "label": "Nested?",
                "condition": {
                    "operator": "or",
                    "conditions": [
                        {"input_id": var_id, "comparator": "is_true"},
                        # Nested compound — should be rejected
                        {
                            "operator": "and",
                            "conditions": [
                                {"input_id": var_id, "comparator": "is_true"},
                                {"input_id": var_id, "comparator": "is_true"},
                            ],
                        },
                    ],
                },
            },
            session_state=session,
        )
        assert result["success"] is False
        assert "nesting" in result["error"].lower() or "compound" in result["error"].lower()
