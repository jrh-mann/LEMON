"""Integration tests for variable synchronisation between tools and orchestrator.

Verifies that the orchestrator's refresh_workflow_from_db() correctly picks up
state changes made by tools (which save directly to the database), and that
the WorkflowValidator accepts chained calculation references.

The old _update_workflow_from_tool_result / _update_analysis_from_tool_result
methods were replaced by a single refresh_workflow_from_db() call that reads
the DB after each tool execution.
"""

import pytest
import tempfile
from pathlib import Path
from uuid import uuid4

from src.backend.agents.orchestrator import Orchestrator, ToolResult
from src.backend.tools import ToolRegistry
from src.backend.storage.workflows import WorkflowStore
from src.backend.validation.workflow_validator import WorkflowValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_orchestrator_with_db(tmp_path, **db_overrides):
    """Create an Orchestrator wired to a real WorkflowStore.

    Creates a workflow in the DB and configures the orchestrator to point at it.
    Returns (orchestrator, workflow_id, workflow_store).
    """
    db_path = tmp_path / f"test_{uuid4().hex[:8]}.sqlite"
    store = WorkflowStore(db_path)
    user_id = "test_user"
    wf_id = f"wf_{uuid4().hex[:8]}"

    store.create_workflow(
        workflow_id=wf_id,
        user_id=user_id,
        name="Test",
        description="",
        output_type="string",
    )

    # Apply any overrides to the DB record (nodes, edges, inputs/variables)
    update_kwargs = {}
    if "nodes" in db_overrides:
        update_kwargs["nodes"] = db_overrides["nodes"]
    if "edges" in db_overrides:
        update_kwargs["edges"] = db_overrides["edges"]
    if "variables" in db_overrides:
        update_kwargs["inputs"] = db_overrides["variables"]
    if "outputs" in db_overrides:
        update_kwargs["outputs"] = db_overrides["outputs"]
    if update_kwargs:
        store.update_workflow(wf_id, user_id, **update_kwargs)

    registry = ToolRegistry()
    orch = Orchestrator(registry)
    orch.workflow_store = store
    orch.user_id = user_id
    orch.current_workflow_id = wf_id
    return orch, wf_id, store


def _make_orchestrator(**workflow_overrides) -> Orchestrator:
    """Create an Orchestrator with a given workflow state (no DB, for validator tests)."""
    registry = ToolRegistry()
    orch = Orchestrator(registry)
    for k, v in workflow_overrides.items():
        orch.workflow[k] = v
    return orch


def _ok_result(tool_name: str = "add_node", **data_overrides) -> ToolResult:
    """A successful ToolResult stub."""
    data = {"success": True, **data_overrides}
    return ToolResult(tool=tool_name, data=data, success=True, message="OK")


def _calc_node(node_id: str, label: str, output_name: str,
               operator: str = "add", operands: list | None = None) -> dict:
    """Build a minimal calculation node dict."""
    return {
        "id": node_id,
        "type": "calculation",
        "label": label,
        "x": 0, "y": 0,
        "calculation": {
            "output": {"name": output_name},
            "operator": operator,
            "operands": operands or [
                {"kind": "literal", "value": 1},
                {"kind": "literal", "value": 2},
            ],
        },
    }


def _variable(name: str, var_type: str = "number", source: str = "calculated",
              source_node_id: str = "") -> dict:
    """Build a minimal variable dict."""
    return {
        "id": f"var_{name}_{var_type}",
        "name": name,
        "type": var_type,
        "source": source,
        "source_node_id": source_node_id,
    }


# ---------------------------------------------------------------------------
# refresh_workflow_from_db: add_node variable sync
# ---------------------------------------------------------------------------

class TestAddNodeVariableSync:
    """Verify refresh_workflow_from_db picks up new variables after add_node saves to DB."""

    def test_new_variables_loaded_from_db(self, tmp_path):
        """After a tool saves a new calc variable to DB, refresh picks it up."""
        calc_var = _variable("calc_total", source_node_id="n1")
        node = _calc_node("n1", "Total", "calc_total")

        orch, wf_id, store = _make_orchestrator_with_db(
            tmp_path, nodes=[node], variables=[calc_var],
        )

        # Orchestrator starts empty, DB has the data
        assert orch.workflow["variables"] == []

        orch.refresh_workflow_from_db()

        assert len(orch.workflow["variables"]) == 1
        assert orch.workflow["variables"][0]["name"] == "calc_total"

    def test_no_new_variables_is_harmless(self, tmp_path):
        """refresh_workflow_from_db with no variables in DB leaves variables empty."""
        node = {"id": "n1", "type": "process", "label": "Step", "x": 0, "y": 0}
        orch, wf_id, store = _make_orchestrator_with_db(tmp_path, nodes=[node])

        orch.refresh_workflow_from_db()

        assert len(orch.workflow["variables"]) == 0
        assert len(orch.workflow["nodes"]) == 1

    def test_existing_variables_loaded_alongside_new(self, tmp_path):
        """refresh_workflow_from_db loads all variables from DB."""
        existing = _variable("patient_age", source="user_defined")
        new_var = _variable("calc_bmi", source_node_id="n1")
        node = _calc_node("n1", "BMI", "calc_bmi")

        orch, wf_id, store = _make_orchestrator_with_db(
            tmp_path, nodes=[node], variables=[existing, new_var],
        )

        orch.refresh_workflow_from_db()

        assert len(orch.workflow["variables"]) == 2
        names = {v["name"] for v in orch.workflow["variables"]}
        assert names == {"patient_age", "calc_bmi"}


# ---------------------------------------------------------------------------
# refresh_workflow_from_db: batch_edit variable sync
# ---------------------------------------------------------------------------

class TestBatchEditVariableSync:
    """Verify refresh_workflow_from_db picks up variables after batch_edit saves to DB."""

    def test_variables_loaded_from_db(self, tmp_path):
        """After batch_edit saves variables to DB, refresh picks them up."""
        calc_var = _variable("calc_egfr", source_node_id="n1")
        node = _calc_node("n1", "eGFR", "calc_egfr")

        orch, wf_id, store = _make_orchestrator_with_db(
            tmp_path, nodes=[node], variables=[calc_var],
        )

        orch.refresh_workflow_from_db()

        assert len(orch.workflow["variables"]) == 1
        assert orch.workflow["variables"][0]["name"] == "calc_egfr"

    def test_no_variables_preserves_empty(self, tmp_path):
        """refresh_workflow_from_db with no variables in DB gives empty list."""
        node = {"id": "n1", "type": "process", "label": "Step", "x": 0, "y": 0}
        orch, wf_id, store = _make_orchestrator_with_db(tmp_path, nodes=[node])

        # Pre-set local state that should be overwritten
        orch.workflow["variables"] = [_variable("patient_age", source="user_defined")]

        orch.refresh_workflow_from_db()

        # DB has no variables, so local state is overwritten to empty
        assert len(orch.workflow["variables"]) == 0

    def test_nodes_and_edges_also_loaded(self, tmp_path):
        """refresh_workflow_from_db loads nodes and edges from DB."""
        node = {"id": "n1", "type": "start", "label": "Start", "x": 0, "y": 0}
        edge = {"id": "e1", "from": "n1", "to": "n2", "label": ""}

        orch, wf_id, store = _make_orchestrator_with_db(
            tmp_path, nodes=[node], edges=[edge],
        )

        orch.refresh_workflow_from_db()

        assert len(orch.workflow["nodes"]) == 1
        assert len(orch.workflow["edges"]) == 1


# ---------------------------------------------------------------------------
# Post-tool validation: chained calc doesn't fail after sync
# ---------------------------------------------------------------------------

class TestPostToolValidationWithSyncedVars:
    """Verify _post_tool_validate passes when calc vars are properly synced."""

    def test_chained_calc_passes_after_variable_sync(self):
        """A second calc referencing the first's output should pass post-tool validation
        when variables have been synced by refresh_workflow_from_db."""
        calc1_var = _variable("calc_egfr", source_node_id="n_calc1")
        calc1_node = _calc_node("n_calc1", "eGFR", "calc_egfr")

        # Second calc references first calc's output by name
        calc2_node = _calc_node(
            "n_calc2", "Adjusted eGFR", "calc_adjusted_egfr",
            operator="multiply",
            operands=[
                {"kind": "variable", "ref": "calc_egfr"},
                {"kind": "literal", "value": 0.742},
            ],
        )
        calc2_var = _variable("calc_adjusted_egfr", source_node_id="n_calc2")

        orch = _make_orchestrator(
            nodes=[calc1_node, calc2_node],
            edges=[],
            variables=[calc1_var, calc2_var],
        )

        result = _ok_result()
        validated = orch._post_tool_validate(result)
        assert validated.success is True

    def test_chained_calc_fails_without_variable_sync(self):
        """Without synced variables, a chained calc reference would have failed
        before Fix 2 (derived_output_vars). Now it passes via the validator fix."""
        calc1_node = _calc_node("n_calc1", "eGFR", "calc_egfr")
        calc2_node = _calc_node(
            "n_calc2", "Adjusted", "calc_adjusted",
            operator="multiply",
            operands=[
                {"kind": "variable", "ref": "calc_egfr"},
                {"kind": "literal", "value": 0.742},
            ],
        )

        # NO variables synced — this tests the validator's derived_output_vars path
        orch = _make_orchestrator(
            nodes=[calc1_node, calc2_node],
            edges=[],
            variables=[],  # Empty — simulates stale state
        )

        result = _ok_result()
        validated = orch._post_tool_validate(result)
        # Fix 2 ensures the validator infers calc_egfr from node definitions
        assert validated.success is True


# ---------------------------------------------------------------------------
# Fix 2: WorkflowValidator accepts chained calculation operand refs
# ---------------------------------------------------------------------------

class TestValidatorChainedCalculations:
    """Verify WorkflowValidator._validate_calculation_node uses derived_output_vars."""

    def setup_method(self):
        self.validator = WorkflowValidator()

    def test_calc_referencing_another_calc_output_is_valid(self):
        """Calculation operand referencing another calc's output should be valid."""
        workflow = {
            "nodes": [
                _calc_node("n1", "Base", "base_value"),
                _calc_node("n2", "Derived", "derived_value",
                           operator="multiply",
                           operands=[
                               {"kind": "variable", "ref": "base_value"},
                               {"kind": "literal", "value": 2},
                           ]),
            ],
            "edges": [],
            "variables": [],  # No explicit variables — both are derived
        }
        is_valid, errors = self.validator.validate(workflow, strict=False)
        calc_errors = [e for e in errors if e.code == "CALCULATION_INVALID_OPERAND_REF"]
        assert len(calc_errors) == 0

    def test_calc_referencing_nonexistent_var_still_fails(self):
        """Calc operand referencing a variable that doesn't exist should still fail."""
        workflow = {
            "nodes": [
                _calc_node("n1", "Bad Ref", "bad_result",
                           operator="add",
                           operands=[
                               {"kind": "variable", "ref": "nonexistent_var"},
                               {"kind": "literal", "value": 1},
                           ]),
            ],
            "edges": [],
            "variables": [],
        }
        is_valid, errors = self.validator.validate(workflow, strict=False)
        calc_errors = [e for e in errors if e.code == "CALCULATION_INVALID_OPERAND_REF"]
        assert len(calc_errors) == 1

    def test_calc_referencing_subprocess_output_is_valid(self):
        """Calc operand referencing a subprocess node's output_variable is valid."""
        workflow = {
            "nodes": [
                {"id": "n_sub", "type": "subprocess", "label": "Get eGFR",
                 "x": 0, "y": 0, "subworkflow_id": "wf_egfr",
                 "output_variable": "egfr_result"},
                _calc_node("n_calc", "Adjust", "adjusted_egfr",
                           operator="multiply",
                           operands=[
                               {"kind": "variable", "ref": "egfr_result"},
                               {"kind": "literal", "value": 0.742},
                           ]),
            ],
            "edges": [],
            "variables": [],
        }
        is_valid, errors = self.validator.validate(workflow, strict=False)
        calc_errors = [e for e in errors if e.code == "CALCULATION_INVALID_OPERAND_REF"]
        assert len(calc_errors) == 0

    def test_three_chained_calcs_all_valid(self):
        """Three chained calculations where each references the previous output."""
        workflow = {
            "nodes": [
                _calc_node("n1", "Step1", "step1_out"),
                _calc_node("n2", "Step2", "step2_out",
                           operator="multiply",
                           operands=[
                               {"kind": "variable", "ref": "step1_out"},
                               {"kind": "literal", "value": 2},
                           ]),
                _calc_node("n3", "Step3", "step3_out",
                           operator="add",
                           operands=[
                               {"kind": "variable", "ref": "step1_out"},
                               {"kind": "variable", "ref": "step2_out"},
                           ]),
            ],
            "edges": [],
            "variables": [],
        }
        is_valid, errors = self.validator.validate(workflow, strict=False)
        calc_errors = [e for e in errors if e.code == "CALCULATION_INVALID_OPERAND_REF"]
        assert len(calc_errors) == 0

    def test_calc_referencing_explicit_variable_still_works(self):
        """Calc referencing a user-defined variable (in variables list) still works."""
        workflow = {
            "nodes": [
                _calc_node("n1", "BMI", "bmi_result",
                           operator="divide",
                           operands=[
                               {"kind": "variable", "ref": "patient_weight"},
                               {"kind": "variable", "ref": "var_height_number"},
                           ]),
            ],
            "edges": [],
            "variables": [
                _variable("patient_weight", source="user_defined"),
                {"id": "var_height_number", "name": "height", "type": "number",
                 "source": "user_defined"},
            ],
        }
        is_valid, errors = self.validator.validate(workflow, strict=False)
        calc_errors = [e for e in errors if e.code == "CALCULATION_INVALID_OPERAND_REF"]
        assert len(calc_errors) == 0


# ---------------------------------------------------------------------------
# refresh_workflow_from_db: delete_node cleans up derived variables
# ---------------------------------------------------------------------------

class TestDeleteNodeVariableCleanup:
    """Verify refresh_workflow_from_db reflects variable removal after delete_node."""

    def test_calc_variable_removed_after_node_delete(self, tmp_path):
        """After tool deletes a calc node and its variable from DB, refresh reflects it."""
        input_var = _variable("patient_age", source="input", source_node_id="")

        # DB initially has calc node + variable; tool will have already removed them
        # Simulate post-tool DB state: node and calc variable gone
        orch, wf_id, store = _make_orchestrator_with_db(
            tmp_path, nodes=[], variables=[input_var],
        )

        # Pre-set orchestrator with stale state (both variables)
        calc_var = _variable("calc_total", source_node_id="n_calc")
        orch.workflow["variables"] = [input_var, calc_var]

        orch.refresh_workflow_from_db()

        # After refresh, only input_var remains (DB truth)
        assert len(orch.workflow["variables"]) == 1
        assert orch.workflow["variables"][0]["name"] == "patient_age"

    def test_subprocess_variable_removed_after_node_delete(self, tmp_path):
        """After tool deletes a subprocess node, refresh reflects variable removal."""
        orch, wf_id, store = _make_orchestrator_with_db(
            tmp_path, nodes=[], variables=[],
        )

        # Pre-set stale local state
        sub_var = _variable("egfr_result", var_type="number",
                            source="subprocess", source_node_id="n_sub")
        orch.workflow["variables"] = [sub_var]

        orch.refresh_workflow_from_db()

        assert len(orch.workflow["variables"]) == 0

    def test_delete_process_node_no_variable_change(self, tmp_path):
        """Deleting a process node should not affect variables in DB."""
        input_var = _variable("age", source="input")
        orch, wf_id, store = _make_orchestrator_with_db(
            tmp_path, nodes=[], variables=[input_var],
        )

        orch.refresh_workflow_from_db()

        assert len(orch.workflow["variables"]) == 1


# ---------------------------------------------------------------------------
# refresh_workflow_from_db: modify_node variable changes
# ---------------------------------------------------------------------------

class TestModifyNodeVariableSync:
    """Verify refresh_workflow_from_db reflects variable changes after modify_node."""

    def test_calc_output_rename_reflected(self, tmp_path):
        """After tool renames a calc output in DB, refresh picks up the new variable."""
        new_var = _variable("calc_grand_total", source_node_id="n_calc")
        node = _calc_node("n_calc", "Grand Total", "calc_grand_total")

        orch, wf_id, store = _make_orchestrator_with_db(
            tmp_path, nodes=[node], variables=[new_var],
        )

        # Pre-set stale orchestrator state with old variable
        old_var = _variable("calc_total", source_node_id="n_calc")
        orch.workflow["variables"] = [old_var]

        orch.refresh_workflow_from_db()

        assert len(orch.workflow["variables"]) == 1
        assert orch.workflow["variables"][0]["name"] == "calc_grand_total"

    def test_type_change_from_calc_removes_variable(self, tmp_path):
        """After tool changes node type from calc to process, refresh shows no variables."""
        node = {"id": "n1", "type": "process", "label": "Step", "x": 0, "y": 0}
        orch, wf_id, store = _make_orchestrator_with_db(
            tmp_path, nodes=[node], variables=[],
        )

        # Pre-set stale state
        orch.workflow["variables"] = [_variable("calc_total", source_node_id="n1")]

        orch.refresh_workflow_from_db()

        assert len(orch.workflow["variables"]) == 0

    def test_type_change_to_calc_adds_variable(self, tmp_path):
        """After tool changes node to calc type and adds variable in DB, refresh picks it up."""
        new_var = _variable("calc_result", source_node_id="n1")
        node = _calc_node("n1", "Calculate", "calc_result")

        orch, wf_id, store = _make_orchestrator_with_db(
            tmp_path, nodes=[node], variables=[new_var],
        )

        orch.refresh_workflow_from_db()

        assert len(orch.workflow["variables"]) == 1
        assert orch.workflow["variables"][0]["name"] == "calc_result"

    def test_input_variables_preserved_during_calc_rename(self, tmp_path):
        """After tool renames a calc output in DB, input variables are preserved."""
        input_var = _variable("patient_age", source="input")
        new_calc_var = _variable("calc_bmi_adjusted", source_node_id="n_calc")
        node = _calc_node("n_calc", "BMI", "calc_bmi_adjusted")

        orch, wf_id, store = _make_orchestrator_with_db(
            tmp_path, nodes=[node], variables=[input_var, new_calc_var],
        )

        orch.refresh_workflow_from_db()

        assert len(orch.workflow["variables"]) == 2
        names = {v["name"] for v in orch.workflow["variables"]}
        assert names == {"patient_age", "calc_bmi_adjusted"}


# ---------------------------------------------------------------------------
# refresh_workflow_from_db: edge cases
# ---------------------------------------------------------------------------

class TestRefreshEdgeCases:
    """Verify refresh_workflow_from_db handles edge cases gracefully."""

    def test_no_workflow_store_is_noop(self):
        """refresh_workflow_from_db without workflow_store does nothing."""
        orch = _make_orchestrator(nodes=[], edges=[], variables=[])
        orch.workflow["variables"] = [_variable("age", source="input")]

        orch.refresh_workflow_from_db()

        # State unchanged since no DB to read from
        assert len(orch.workflow["variables"]) == 1

    def test_no_workflow_id_is_noop(self, tmp_path):
        """refresh_workflow_from_db without current_workflow_id does nothing."""
        db_path = tmp_path / "test.sqlite"
        store = WorkflowStore(db_path)

        orch = _make_orchestrator(nodes=[], edges=[], variables=[])
        orch.workflow_store = store
        orch.user_id = "test_user"
        # No current_workflow_id set

        orch.workflow["variables"] = [_variable("age", source="input")]
        orch.refresh_workflow_from_db()

        # State unchanged
        assert len(orch.workflow["variables"]) == 1

    def test_missing_workflow_record_is_noop(self, tmp_path):
        """refresh_workflow_from_db with non-existent workflow ID does nothing."""
        db_path = tmp_path / "test.sqlite"
        store = WorkflowStore(db_path)

        orch = _make_orchestrator(nodes=[], edges=[], variables=[])
        orch.workflow_store = store
        orch.user_id = "test_user"
        orch.current_workflow_id = "wf_nonexistent"

        orch.workflow["variables"] = [_variable("age", source="input")]
        orch.refresh_workflow_from_db()

        # State unchanged since record not found
        assert len(orch.workflow["variables"]) == 1


# ---------------------------------------------------------------------------
# Fix F: lazy re-derive subprocess variable types on workflow load
# ---------------------------------------------------------------------------

class TestLazyReDeriveSubprocessVariables:
    """Verify load_workflow_for_tool() re-derives subprocess variable types.

    When a subworkflow's output type changes (e.g., via set_workflow_output),
    calling workflows should pick up the new type automatically on next load.
    """

    def test_subprocess_var_type_updated_when_subworkflow_output_changes(
        self, workflow_store, test_user_id,
    ):
        """Loading a workflow should update stale subprocess variable types
        to match the subworkflow's current output type."""
        from src.backend.tools.workflow_edit.helpers import load_workflow_for_tool
        from src.backend.tools.workflow_input.add import generate_variable_id
        from tests.conftest import make_session_with_workflow

        # Create subworkflow with output type "string"
        sub_id, _ = make_session_with_workflow(
            workflow_store, test_user_id, name="Sub WF",
            output_type="string",
        )
        # Set output definition on subworkflow
        workflow_store.update_workflow(
            sub_id, test_user_id,
            outputs=[{"name": "result", "type": "string"}],
        )

        # Create parent workflow with a subprocess node pointing to sub_id
        # The derived variable was originally registered as type "string"
        old_var_id = generate_variable_id("sub_result", "string", "subprocess")
        sub_node = {
            "id": "n_sub", "type": "subprocess", "label": "Run Sub",
            "x": 0, "y": 0,
            "subworkflow_id": sub_id,
            "output_variable": "sub_result",
        }
        sub_var = {
            "id": old_var_id,
            "name": "sub_result",
            "type": "string",
            "source": "subprocess",
            "source_node_id": "n_sub",
            "subworkflow_id": sub_id,
        }
        parent_id, session_state = make_session_with_workflow(
            workflow_store, test_user_id, name="Parent WF",
            nodes=[sub_node], variables=[sub_var],
        )

        # Now change the subworkflow's output type to "number"
        workflow_store.update_workflow(
            sub_id, test_user_id,
            outputs=[{"name": "result", "type": "number"}],
        )

        # Load parent workflow — lazy re-derive should update the variable
        data, err = load_workflow_for_tool(parent_id, session_state)
        assert err is None
        assert len(data["variables"]) == 1

        updated_var = data["variables"][0]
        assert updated_var["type"] == "number", (
            f"Expected type 'number' after subworkflow change, got '{updated_var['type']}'"
        )
        expected_id = generate_variable_id("sub_result", "number", "subprocess")
        assert updated_var["id"] == expected_id

    def test_subprocess_var_id_regenerated_on_type_change(
        self, workflow_store, test_user_id,
    ):
        """Variable ID should change because it encodes the type."""
        from src.backend.tools.workflow_edit.helpers import load_workflow_for_tool
        from src.backend.tools.workflow_input.add import generate_variable_id
        from tests.conftest import make_session_with_workflow

        sub_id, _ = make_session_with_workflow(
            workflow_store, test_user_id, name="Sub WF",
            output_type="number",
        )
        workflow_store.update_workflow(
            sub_id, test_user_id,
            outputs=[{"name": "score", "type": "number"}],
        )

        old_var_id = generate_variable_id("score_output", "number", "subprocess")
        sub_node = {
            "id": "n_sub", "type": "subprocess", "label": "Calc Score",
            "x": 0, "y": 0,
            "subworkflow_id": sub_id,
            "output_variable": "score_output",
        }
        sub_var = {
            "id": old_var_id,
            "name": "score_output",
            "type": "number",
            "source": "subprocess",
            "source_node_id": "n_sub",
        }
        parent_id, session_state = make_session_with_workflow(
            workflow_store, test_user_id, name="Parent",
            nodes=[sub_node], variables=[sub_var],
        )

        # Change subworkflow output to bool
        workflow_store.update_workflow(
            sub_id, test_user_id,
            outputs=[{"name": "score", "type": "bool"}],
        )

        data, _ = load_workflow_for_tool(parent_id, session_state)
        updated_var = data["variables"][0]
        new_expected_id = generate_variable_id("score_output", "bool", "subprocess")
        assert updated_var["id"] == new_expected_id
        assert updated_var["id"] != old_var_id

    def test_non_subprocess_variables_untouched(
        self, workflow_store, test_user_id,
    ):
        """Input and calculated variables should not be modified by re-derive."""
        from src.backend.tools.workflow_edit.helpers import load_workflow_for_tool
        from tests.conftest import make_session_with_workflow

        input_var = {
            "id": "var_age_number", "name": "age", "type": "number",
            "source": "input", "source_node_id": "",
        }
        calc_var = {
            "id": "var_calc_bmi_number", "name": "calc_bmi", "type": "number",
            "source": "calculated", "source_node_id": "n_calc",
        }
        calc_node = {
            "id": "n_calc", "type": "calculation", "label": "BMI",
            "x": 0, "y": 0,
            "calculation": {
                "output": {"name": "calc_bmi"},
                "operator": "divide",
                "operands": [
                    {"kind": "literal", "value": 70},
                    {"kind": "literal", "value": 1.75},
                ],
            },
        }
        wf_id, session_state = make_session_with_workflow(
            workflow_store, test_user_id, name="No Sub WF",
            nodes=[calc_node], variables=[input_var, calc_var],
        )

        data, err = load_workflow_for_tool(wf_id, session_state)
        assert err is None
        assert len(data["variables"]) == 2
        # Both should be unchanged
        types = {v["name"]: v["type"] for v in data["variables"]}
        assert types == {"age": "number", "calc_bmi": "number"}

    def test_subprocess_node_without_subworkflow_id_no_crash(
        self, workflow_store, test_user_id,
    ):
        """A subprocess node with missing subworkflow_id should not crash re-derive."""
        from src.backend.tools.workflow_edit.helpers import load_workflow_for_tool
        from tests.conftest import make_session_with_workflow

        sub_node = {
            "id": "n_sub", "type": "subprocess", "label": "Placeholder",
            "x": 0, "y": 0,
            # No subworkflow_id
            "output_variable": "placeholder_out",
        }
        sub_var = {
            "id": "var_sub_placeholder_out_string", "name": "placeholder_out",
            "type": "string", "source": "subprocess", "source_node_id": "n_sub",
        }
        wf_id, session_state = make_session_with_workflow(
            workflow_store, test_user_id, name="Partial Sub",
            nodes=[sub_node], variables=[sub_var],
        )

        data, err = load_workflow_for_tool(wf_id, session_state)
        assert err is None
        # Variable should remain unchanged (can't look up type without subworkflow_id)
        assert data["variables"][0]["type"] == "string"

    def test_updated_variables_persisted_to_db(
        self, workflow_store, test_user_id,
    ):
        """Re-derived variable types should be saved back to the database."""
        from src.backend.tools.workflow_edit.helpers import load_workflow_for_tool
        from src.backend.tools.workflow_input.add import generate_variable_id
        from tests.conftest import make_session_with_workflow

        # Create subworkflow with output type "string"
        sub_id, _ = make_session_with_workflow(
            workflow_store, test_user_id, name="Sub WF",
        )
        workflow_store.update_workflow(
            sub_id, test_user_id,
            outputs=[{"name": "val", "type": "string"}],
        )

        sub_node = {
            "id": "n_sub", "type": "subprocess", "label": "Get Val",
            "x": 0, "y": 0,
            "subworkflow_id": sub_id,
            "output_variable": "val_out",
        }
        old_var_id = generate_variable_id("val_out", "string", "subprocess")
        sub_var = {
            "id": old_var_id, "name": "val_out", "type": "string",
            "source": "subprocess", "source_node_id": "n_sub",
        }
        parent_id, session_state = make_session_with_workflow(
            workflow_store, test_user_id, name="Parent",
            nodes=[sub_node], variables=[sub_var],
        )

        # Change subworkflow output type
        workflow_store.update_workflow(
            sub_id, test_user_id,
            outputs=[{"name": "val", "type": "number"}],
        )

        # First load triggers re-derive
        load_workflow_for_tool(parent_id, session_state)

        # Second load should see the persisted update (no re-derive needed)
        record = workflow_store.get_workflow(parent_id, test_user_id)
        assert len(record.inputs) == 1
        assert record.inputs[0]["type"] == "number"
        expected_id = generate_variable_id("val_out", "number", "subprocess")
        assert record.inputs[0]["id"] == expected_id

    def test_no_db_write_when_types_already_match(
        self, workflow_store, test_user_id,
    ):
        """If subprocess variable types already match, no DB write should occur."""
        from src.backend.tools.workflow_edit.helpers import load_workflow_for_tool
        from src.backend.tools.workflow_input.add import generate_variable_id
        from tests.conftest import make_session_with_workflow
        from unittest.mock import patch

        sub_id, _ = make_session_with_workflow(
            workflow_store, test_user_id, name="Sub WF",
        )
        workflow_store.update_workflow(
            sub_id, test_user_id,
            outputs=[{"name": "val", "type": "number"}],
        )

        sub_node = {
            "id": "n_sub", "type": "subprocess", "label": "Get Val",
            "x": 0, "y": 0,
            "subworkflow_id": sub_id,
            "output_variable": "val_out",
        }
        var_id = generate_variable_id("val_out", "number", "subprocess")
        sub_var = {
            "id": var_id, "name": "val_out", "type": "number",
            "source": "subprocess", "source_node_id": "n_sub",
        }
        parent_id, session_state = make_session_with_workflow(
            workflow_store, test_user_id, name="Parent",
            nodes=[sub_node], variables=[sub_var],
        )

        # Patch save_workflow_changes to detect if it's called
        with patch(
            "src.backend.tools.workflow_edit.helpers.save_workflow_changes"
        ) as mock_save:
            load_workflow_for_tool(parent_id, session_state)
            mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# Socket-level: analysis_updated emitted for edit tools with variable changes
# ---------------------------------------------------------------------------

class TestWsVariableSyncOnEditTools:
    """Verify ws_chat emits analysis_updated when WORKFLOW_EDIT_TOOLS
    produce new_variables or removed_variable_ids, so the frontend's
    Variables tab stays in sync without waiting for a WORKFLOW_INPUT_TOOL."""

    def _make_task(self):
        """Build a minimal ChatTask with a mock EventSink and convo."""
        from unittest.mock import Mock, MagicMock
        from src.backend.tasks.chat_task import ChatTask
        from src.backend.tasks.sse import EventSink

        mock_sink = MagicMock(spec=EventSink)
        mock_sink.is_closed = False
        convo = MagicMock()
        # Orchestrator's workflow_analysis property returns variables/outputs
        convo.orchestrator.workflow_analysis = {
            "variables": [_variable("age", source="input")],
            "outputs": [],
        }

        task = ChatTask(
            sink=mock_sink,
            conversation_store=MagicMock(),
            repo_root=MagicMock(),
            workflow_store=MagicMock(),
            user_id="test_user",
            task_id="task_1",
            message="test",
            conversation_id=None,
            files_data=[],
            workflow=None,
            analysis=None,
        )
        task.convo = convo
        return task, mock_sink

    def test_analysis_updated_emitted_for_add_node_with_new_variables(self):
        """add_node creating a calc node should emit analysis_updated."""
        task, mock_sink = self._make_task()
        result = {
            "success": True,
            "action": "add_node",
            "node": _calc_node("n1", "Total", "calc_total"),
            "new_variables": [_variable("calc_total", source_node_id="n1")],
        }

        # Simulate tool_start then tool_complete
        task.on_tool_event("tool_start", "add_node", {"type": "calculation"}, None)
        task.on_tool_event("tool_complete", "add_node", {}, result)

        # Should emit both workflow_update AND analysis_updated
        # sink.push(event, payload) — event is args[0]
        events = [call.args[0] for call in mock_sink.push.call_args_list]
        assert "workflow_update" in events
        assert "analysis_updated" in events

    def test_analysis_updated_emitted_for_delete_node_with_removed_variables(self):
        """delete_node removing a calc node should emit analysis_updated."""
        task, mock_sink = self._make_task()
        result = {
            "success": True,
            "action": "delete_node",
            "node_id": "n1",
            "removed_variable_ids": ["var_calc_total_number"],
        }

        task.on_tool_event("tool_start", "delete_node", {"node_id": "n1"}, None)
        task.on_tool_event("tool_complete", "delete_node", {}, result)

        events = [call.args[0] for call in mock_sink.push.call_args_list]
        assert "workflow_update" in events
        assert "analysis_updated" in events

    def test_no_analysis_updated_for_edit_tool_without_variable_changes(self):
        """add_node for a process node (no variable changes) should NOT emit analysis_updated."""
        task, mock_sink = self._make_task()
        result = {
            "success": True,
            "action": "add_node",
            "node": {"id": "n1", "type": "process", "label": "Step", "x": 0, "y": 0},
        }

        task.on_tool_event("tool_start", "add_node", {"type": "process"}, None)
        task.on_tool_event("tool_complete", "add_node", {}, result)

        events = [call.args[0] for call in mock_sink.push.call_args_list]
        assert "workflow_update" in events
        assert "analysis_updated" not in events

    def test_analysis_updated_payload_has_variables_and_outputs(self):
        """analysis_updated should carry the current variables and outputs."""
        task, mock_sink = self._make_task()
        result = {
            "success": True,
            "action": "add_node",
            "node": _calc_node("n1", "BMI", "calc_bmi"),
            "new_variables": [_variable("calc_bmi", source_node_id="n1")],
        }

        task.on_tool_event("tool_start", "add_node", {"type": "calculation"}, None)
        task.on_tool_event("tool_complete", "add_node", {}, result)

        # Find the analysis_updated push call
        # sink.push(event, payload) — event is args[0], payload is args[1]
        analysis_calls = [
            call for call in mock_sink.push.call_args_list
            if call.args[0] == "analysis_updated"
        ]
        assert len(analysis_calls) == 1
        payload = analysis_calls[0].args[1]
        assert "variables" in payload
        assert "outputs" in payload
        assert "task_id" in payload

    def test_modify_node_with_both_new_and_removed_emits_analysis_updated(self):
        """modify_node renaming a calc output (both new_variables and removed_variable_ids)
        should emit analysis_updated."""
        task, mock_sink = self._make_task()
        result = {
            "success": True,
            "action": "modify_node",
            "node": _calc_node("n1", "Grand Total", "calc_grand_total"),
            "removed_variable_ids": ["var_calc_total_number"],
            "new_variables": [_variable("calc_grand_total", source_node_id="n1")],
        }

        task.on_tool_event("tool_start", "modify_node", {"node_id": "n1"}, None)
        task.on_tool_event("tool_complete", "modify_node", {}, result)

        events = [call.args[0] for call in mock_sink.push.call_args_list]
        assert "workflow_update" in events
        assert "analysis_updated" in events
