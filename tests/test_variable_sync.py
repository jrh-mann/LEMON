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
