"""Integration tests for variable synchronisation between tools and orchestrator.

Verifies that auto-registered variables (from calculation and subprocess nodes)
are correctly synced back to the orchestrator's in-memory workflow state, and
that the WorkflowValidator accepts chained calculation references.
"""

import pytest

from src.backend.agents.orchestrator import Orchestrator, ToolResult
from src.backend.tools import ToolRegistry
from src.backend.validation.workflow_validator import WorkflowValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_orchestrator(**workflow_overrides) -> Orchestrator:
    """Create an Orchestrator with a given workflow state (no real tools needed)."""
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
# Fix 1b: add_node syncs new_variables to orchestrator
# ---------------------------------------------------------------------------

class TestAddNodeVariableSync:
    """Verify _update_workflow_from_tool_result syncs new_variables for add_node."""

    def test_new_variables_appended_to_workflow(self):
        """add_node result with new_variables should update orchestrator variables."""
        orch = _make_orchestrator(nodes=[], edges=[], variables=[])
        calc_var = _variable("calc_total", source_node_id="n1")
        node = _calc_node("n1", "Total", "calc_total")

        orch._update_workflow_from_tool_result("add_node", {
            "node": node,
            "new_variables": [calc_var],
        })

        assert len(orch.workflow["variables"]) == 1
        assert orch.workflow["variables"][0]["name"] == "calc_total"

    def test_no_new_variables_is_harmless(self):
        """add_node result without new_variables should not break."""
        orch = _make_orchestrator(nodes=[], edges=[], variables=[])
        node = {"id": "n1", "type": "process", "label": "Step", "x": 0, "y": 0}

        orch._update_workflow_from_tool_result("add_node", {"node": node})

        assert len(orch.workflow["variables"]) == 0
        assert len(orch.workflow["nodes"]) == 1

    def test_existing_variables_preserved(self):
        """add_node should append, not replace, existing variables."""
        existing = _variable("patient_age", source="user_defined")
        orch = _make_orchestrator(nodes=[], edges=[], variables=[existing])
        new_var = _variable("calc_bmi", source_node_id="n1")
        node = _calc_node("n1", "BMI", "calc_bmi")

        orch._update_workflow_from_tool_result("add_node", {
            "node": node,
            "new_variables": [new_var],
        })

        assert len(orch.workflow["variables"]) == 2
        assert orch.workflow["variables"][0]["name"] == "patient_age"
        assert orch.workflow["variables"][1]["name"] == "calc_bmi"


# ---------------------------------------------------------------------------
# Fix 1c: batch_edit_workflow syncs variables to orchestrator
# ---------------------------------------------------------------------------

class TestBatchEditVariableSync:
    """Verify _update_workflow_from_tool_result syncs variables for batch_edit."""

    def test_variables_synced_from_workflow_analysis(self):
        """batch_edit result with workflow_analysis.variables should update orchestrator."""
        orch = _make_orchestrator(nodes=[], edges=[], variables=[])
        calc_var = _variable("calc_egfr", source_node_id="n1")

        orch._update_workflow_from_tool_result("batch_edit_workflow", {
            "workflow": {
                "nodes": [_calc_node("n1", "eGFR", "calc_egfr")],
                "edges": [],
            },
            "workflow_analysis": {
                "variables": [calc_var],
            },
        })

        assert len(orch.workflow["variables"]) == 1
        assert orch.workflow["variables"][0]["name"] == "calc_egfr"

    def test_no_workflow_analysis_is_harmless(self):
        """batch_edit result without workflow_analysis should not touch variables."""
        existing = _variable("patient_age", source="user_defined")
        orch = _make_orchestrator(nodes=[], edges=[], variables=[existing])

        orch._update_workflow_from_tool_result("batch_edit_workflow", {
            "workflow": {
                "nodes": [{"id": "n1", "type": "process", "label": "Step", "x": 0, "y": 0}],
                "edges": [],
            },
        })

        # Variables unchanged
        assert len(orch.workflow["variables"]) == 1
        assert orch.workflow["variables"][0]["name"] == "patient_age"

    def test_nodes_and_edges_also_synced(self):
        """batch_edit should still sync nodes and edges alongside variables."""
        orch = _make_orchestrator(nodes=[], edges=[], variables=[])
        node = {"id": "n1", "type": "start", "label": "Start", "x": 0, "y": 0}
        edge = {"id": "e1", "from": "n1", "to": "n2", "label": ""}

        orch._update_workflow_from_tool_result("batch_edit_workflow", {
            "workflow": {"nodes": [node], "edges": [edge]},
        })

        assert len(orch.workflow["nodes"]) == 1
        assert len(orch.workflow["edges"]) == 1


# ---------------------------------------------------------------------------
# Fix 1b + post-tool validation: chained calc doesn't fail after sync
# ---------------------------------------------------------------------------

class TestPostToolValidationWithSyncedVars:
    """Verify _post_tool_validate passes when calc vars are properly synced."""

    def test_chained_calc_passes_after_variable_sync(self):
        """A second calc referencing the first's output should pass post-tool validation
        when variables have been synced by _update_workflow_from_tool_result."""
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
# Fix B+E: delete_node cleans up derived variables in orchestrator
# ---------------------------------------------------------------------------

class TestDeleteNodeVariableCleanup:
    """Verify _update_workflow_from_tool_result removes derived vars on delete_node."""

    def test_calc_variable_removed_on_node_delete(self):
        """Deleting a calculation node should remove its derived variable."""
        calc_var = _variable("calc_total", source_node_id="n_calc")
        input_var = _variable("patient_age", source="input", source_node_id="")
        orch = _make_orchestrator(
            nodes=[_calc_node("n_calc", "Total", "calc_total")],
            edges=[],
            variables=[input_var, calc_var],
        )

        orch._update_workflow_from_tool_result("delete_node", {
            "node_id": "n_calc",
            "removed_variable_ids": ["var_calc_total_number"],
        })

        # Calc variable removed, input variable preserved
        assert len(orch.workflow["variables"]) == 1
        assert orch.workflow["variables"][0]["name"] == "patient_age"

    def test_subprocess_variable_removed_on_node_delete(self):
        """Deleting a subprocess node should remove its derived variable."""
        sub_var = _variable("egfr_result", var_type="number",
                            source="subprocess", source_node_id="n_sub")
        orch = _make_orchestrator(
            nodes=[{"id": "n_sub", "type": "subprocess", "label": "Sub",
                    "x": 0, "y": 0, "output_variable": "egfr_result"}],
            edges=[],
            variables=[sub_var],
        )

        orch._update_workflow_from_tool_result("delete_node", {
            "node_id": "n_sub",
            "removed_variable_ids": ["var_egfr_result_number"],
        })

        assert len(orch.workflow["variables"]) == 0

    def test_delete_process_node_no_variable_change(self):
        """Deleting a process node should not affect variables."""
        input_var = _variable("age", source="input")
        orch = _make_orchestrator(
            nodes=[{"id": "n1", "type": "process", "label": "Step", "x": 0, "y": 0}],
            edges=[],
            variables=[input_var],
        )

        orch._update_workflow_from_tool_result("delete_node", {
            "node_id": "n1",
            "removed_variable_ids": [],
        })

        assert len(orch.workflow["variables"]) == 1

    def test_no_removed_ids_field_is_harmless(self):
        """Old-style delete_node result without removed_variable_ids should not break."""
        orch = _make_orchestrator(
            nodes=[{"id": "n1", "type": "process", "label": "Step", "x": 0, "y": 0}],
            edges=[],
            variables=[_variable("age", source="input")],
        )

        orch._update_workflow_from_tool_result("delete_node", {
            "node_id": "n1",
        })

        assert len(orch.workflow["variables"]) == 1


# ---------------------------------------------------------------------------
# Fix A: modify_node syncs derived variable changes to orchestrator
# ---------------------------------------------------------------------------

class TestModifyNodeVariableSync:
    """Verify _update_workflow_from_tool_result handles variable changes on modify_node."""

    def test_calc_output_rename_replaces_variable(self):
        """Renaming a calc node's output should remove old var and add new one."""
        old_var = _variable("calc_total", source_node_id="n_calc")
        orch = _make_orchestrator(
            nodes=[_calc_node("n_calc", "Total", "calc_total")],
            edges=[],
            variables=[old_var],
        )

        # Simulate modify_node result where output name changed
        orch._update_workflow_from_tool_result("modify_node", {
            "node": _calc_node("n_calc", "Grand Total", "calc_grand_total"),
            "removed_variable_ids": ["var_calc_total_number"],
            "new_variables": [_variable("calc_grand_total", source_node_id="n_calc")],
        })

        assert len(orch.workflow["variables"]) == 1
        assert orch.workflow["variables"][0]["name"] == "calc_grand_total"

    def test_type_change_from_calc_removes_variable(self):
        """Changing a node from calculation to process should remove its derived var."""
        calc_var = _variable("calc_total", source_node_id="n1")
        orch = _make_orchestrator(
            nodes=[_calc_node("n1", "Total", "calc_total")],
            edges=[],
            variables=[calc_var],
        )

        orch._update_workflow_from_tool_result("modify_node", {
            "node": {"id": "n1", "type": "process", "label": "Step", "x": 0, "y": 0},
            "removed_variable_ids": ["var_calc_total_number"],
            "new_variables": [],
        })

        assert len(orch.workflow["variables"]) == 0

    def test_type_change_to_calc_adds_variable(self):
        """Changing a node to calculation type should add a derived variable."""
        orch = _make_orchestrator(
            nodes=[{"id": "n1", "type": "process", "label": "Step", "x": 0, "y": 0}],
            edges=[],
            variables=[],
        )

        new_var = _variable("calc_result", source_node_id="n1")
        orch._update_workflow_from_tool_result("modify_node", {
            "node": _calc_node("n1", "Calculate", "calc_result"),
            "removed_variable_ids": [],
            "new_variables": [new_var],
        })

        assert len(orch.workflow["variables"]) == 1
        assert orch.workflow["variables"][0]["name"] == "calc_result"

    def test_modify_non_producing_node_no_variable_change(self):
        """Modifying a process node's label should not affect variables."""
        input_var = _variable("age", source="input")
        orch = _make_orchestrator(
            nodes=[{"id": "n1", "type": "process", "label": "Old", "x": 0, "y": 0}],
            edges=[],
            variables=[input_var],
        )

        orch._update_workflow_from_tool_result("modify_node", {
            "node": {"id": "n1", "type": "process", "label": "New", "x": 0, "y": 0},
        })

        assert len(orch.workflow["variables"]) == 1
        assert orch.workflow["variables"][0]["name"] == "age"

    def test_input_variables_preserved_during_calc_rename(self):
        """Renaming a calc output should not disturb user-defined input variables."""
        input_var = _variable("patient_age", source="input")
        calc_var = _variable("calc_bmi", source_node_id="n_calc")
        orch = _make_orchestrator(
            nodes=[_calc_node("n_calc", "BMI", "calc_bmi")],
            edges=[],
            variables=[input_var, calc_var],
        )

        orch._update_workflow_from_tool_result("modify_node", {
            "node": _calc_node("n_calc", "BMI", "calc_bmi_adjusted"),
            "removed_variable_ids": ["var_calc_bmi_number"],
            "new_variables": [_variable("calc_bmi_adjusted", source_node_id="n_calc")],
        })

        assert len(orch.workflow["variables"]) == 2
        names = {v["name"] for v in orch.workflow["variables"]}
        assert names == {"patient_age", "calc_bmi_adjusted"}


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
