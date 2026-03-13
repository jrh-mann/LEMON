"""Unit tests for eval/functional.py — functional (execution-based) scoring."""

import json
from pathlib import Path

import pytest

from eval.functional import (
    FunctionalScore,
    ThresholdInfo,
    VarMapping,
    _apply_threshold,
    _build_end_node_map,
    _build_threshold_map,
    _build_variable_map,
    _execute_workflow,
    _extra_var_combos,
    _extract_thresholds,
    _flatten_conditions,
    _generate_test_cases,
    _translate_inputs,
    _word_overlap,
    functional_score,
)


# ---------------------------------------------------------------------------
# Fixtures: minimal golden + extracted workflows for testing
# ---------------------------------------------------------------------------

MINIMAL_GOLDEN = {
    "variables": [
        {"id": "var_a_bool", "name": "Has Condition A", "type": "bool",
         "source": "input", "description": "Patient has condition A"},
        {"id": "var_b_number", "name": "Score B", "type": "number",
         "source": "input", "description": "Numeric score B"},
    ],
    "nodes": [
        {"id": "start", "type": "start", "label": "Start Workflow"},
        {"id": "d1", "type": "decision", "label": "Has Condition A?",
         "condition": {"input_id": "var_a_bool", "comparator": "is_true"}},
        {"id": "d2", "type": "decision", "label": "Score B > 10?",
         "condition": {"input_id": "var_b_number", "comparator": "gt", "value": 10}},
        {"id": "end_yes", "type": "end", "label": "Treat with X",
         "output_value": "Treat with X", "output_type": "string"},
        {"id": "end_no", "type": "end", "label": "No Treatment",
         "output_value": "No Treatment", "output_type": "string"},
    ],
    "edges": [
        {"from": "start", "to": "d1", "label": ""},
        {"from": "d1", "to": "d2", "label": "true"},
        {"from": "d1", "to": "end_no", "label": "false"},
        {"from": "d2", "to": "end_yes", "label": "true"},
        {"from": "d2", "to": "end_no", "label": "false"},
    ],
    "outputs": [{"id": "output_rec", "name": "Recommendation", "type": "string"}],
}


def _make_extracted_perfect():
    """Return an extraction with different IDs but identical structure."""
    return {
        "variables": [
            {"id": "v_001", "name": "Has Condition A", "type": "bool",
             "source": "input", "description": "Patient has condition A"},
            {"id": "v_002", "name": "Score B", "type": "number",
             "source": "input", "description": "Numeric score B"},
        ],
        "nodes": [
            {"id": "n_start", "type": "start", "label": "Start Workflow"},
            {"id": "n_d1", "type": "decision", "label": "Has Condition A?",
             "condition": {"input_id": "v_001", "comparator": "is_true"}},
            {"id": "n_d2", "type": "decision", "label": "Score B > 10?",
             "condition": {"input_id": "v_002", "comparator": "gt", "value": 10}},
            {"id": "n_end_yes", "type": "end", "label": "Treat with X",
             "output_value": "Treat with X"},
            {"id": "n_end_no", "type": "end", "label": "No Treatment",
             "output_value": "No Treatment"},
        ],
        "edges": [
            {"from": "n_start", "to": "n_d1", "label": ""},
            {"from": "n_d1", "to": "n_d2", "label": "true"},
            {"from": "n_d1", "to": "n_end_no", "label": "false"},
            {"from": "n_d2", "to": "n_end_yes", "label": "true"},
            {"from": "n_d2", "to": "n_end_no", "label": "false"},
        ],
        "outputs": [],
    }


def _make_extracted_wrong_routing():
    """Extraction that swaps the true/false branches on d1 — functionally wrong."""
    return {
        "variables": [
            {"id": "v_001", "name": "Has Condition A", "type": "bool",
             "source": "input"},
            {"id": "v_002", "name": "Score B", "type": "number",
             "source": "input"},
        ],
        "nodes": [
            {"id": "n_start", "type": "start", "label": "Start Workflow"},
            {"id": "n_d1", "type": "decision", "label": "Has Condition A?",
             "condition": {"input_id": "v_001", "comparator": "is_true"}},
            {"id": "n_d2", "type": "decision", "label": "Score B > 10?",
             "condition": {"input_id": "v_002", "comparator": "gt", "value": 10}},
            {"id": "n_end_yes", "type": "end", "label": "Treat with X"},
            {"id": "n_end_no", "type": "end", "label": "No Treatment"},
        ],
        "edges": [
            {"from": "n_start", "to": "n_d1", "label": ""},
            # SWAPPED: true→end_no, false→d2 (opposite of golden)
            {"from": "n_d1", "to": "n_end_no", "label": "true"},
            {"from": "n_d1", "to": "n_d2", "label": "false"},
            {"from": "n_d2", "to": "n_end_yes", "label": "true"},
            {"from": "n_d2", "to": "n_end_no", "label": "false"},
        ],
        "outputs": [],
    }


EMPTY_WORKFLOW = {"variables": [], "nodes": [], "edges": [], "outputs": []}


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestWordOverlap:
    def test_identical(self):
        assert _word_overlap("Hello World", "Hello World") == 1.0

    def test_reordered(self):
        """Word overlap should handle reordering better than SequenceMatcher."""
        score = _word_overlap("Treatment Optimised", "Optimised on Treatment")
        # "treatment" and "optimised" overlap; "on" doesn't — 2/3 Jaccard.
        assert score == pytest.approx(2 / 3)

    def test_empty(self):
        assert _word_overlap("", "") == 1.0

    def test_disjoint(self):
        assert _word_overlap("Alpha Beta", "Gamma Delta") == 0.0


class TestExtractThresholds:
    def test_extracts_from_conditions(self):
        thresholds = _extract_thresholds(MINIMAL_GOLDEN)
        assert "var_b_number" in thresholds
        assert 10 in thresholds["var_b_number"]

    def test_no_bool_thresholds(self):
        """Bool conditions (is_true/is_false) have no value to extract."""
        thresholds = _extract_thresholds(MINIMAL_GOLDEN)
        assert "var_a_bool" not in thresholds

    def test_compound_condition(self):
        """Thresholds from compound (AND/OR) conditions are extracted."""
        golden = {
            "nodes": [{
                "id": "d1", "type": "decision",
                "condition": {
                    "operator": "and",
                    "conditions": [
                        {"input_id": "var_x", "comparator": "gt", "value": 5},
                        {"input_id": "var_y", "comparator": "lte", "value": 20},
                    ],
                },
            }],
        }
        thresholds = _extract_thresholds(golden)
        assert 5 in thresholds["var_x"]
        assert 20 in thresholds["var_y"]


class TestBuildThresholdMap:
    def test_extracts_first_threshold(self):
        golden = {
            "nodes": [
                {"id": "d1", "type": "decision",
                 "condition": {"input_id": "var_a", "comparator": "lte", "value": 48}},
                {"id": "d2", "type": "decision",
                 "condition": {"input_id": "var_a", "comparator": "gt", "value": 53}},
            ],
        }
        tmap = _build_threshold_map(golden)
        # Should keep the first threshold encountered (lte 48).
        assert tmap["var_a"].comparator == "lte"
        assert tmap["var_a"].value == 48.0

    def test_ignores_bool_conditions(self):
        golden = {
            "nodes": [
                {"id": "d1", "type": "decision",
                 "condition": {"input_id": "var_b", "comparator": "is_true"}},
            ],
        }
        tmap = _build_threshold_map(golden)
        assert "var_b" not in tmap


class TestApplyThreshold:
    def test_lte(self):
        assert _apply_threshold(47, "lte", 48) is True
        assert _apply_threshold(49, "lte", 48) is False

    def test_gt(self):
        assert _apply_threshold(8.0, "gt", 7.5) is True
        assert _apply_threshold(7.0, "gt", 7.5) is False

    def test_gte(self):
        assert _apply_threshold(10, "gte", 10) is True
        assert _apply_threshold(9.9, "gte", 10) is False


class TestFlattenConditions:
    def test_simple(self):
        cond = {"input_id": "x", "comparator": "gt", "value": 5}
        assert _flatten_conditions(cond) == [cond]

    def test_compound(self):
        cond = {
            "operator": "and",
            "conditions": [
                {"input_id": "x", "comparator": "gt", "value": 5},
                {"input_id": "y", "comparator": "lt", "value": 10},
            ],
        }
        result = _flatten_conditions(cond)
        assert len(result) == 2


class TestGenerateTestCases:
    def test_generates_cases(self):
        cases = _generate_test_cases(MINIMAL_GOLDEN)
        assert len(cases) > 0

    def test_bool_values(self):
        """Bool variables should produce True and False test values."""
        cases = _generate_test_cases(MINIMAL_GOLDEN)
        a_values = {c["var_a_bool"] for c in cases}
        assert True in a_values
        assert False in a_values

    def test_number_boundary_values(self):
        """Number variables should include threshold boundary values."""
        cases = _generate_test_cases(MINIMAL_GOLDEN)
        b_values = {c["var_b_number"] for c in cases}
        # Should include below (9.9), at (10), and above (10.1) the threshold.
        assert 9.9 in b_values
        assert 10.0 in b_values
        assert 10.1 in b_values

    def test_enum_values(self):
        golden = {
            "variables": [
                {"id": "var_e", "name": "Choice", "type": "enum",
                 "source": "input", "enum_values": ["A", "B", "C"]},
            ],
            "nodes": [],
        }
        cases = _generate_test_cases(golden)
        e_values = {c["var_e"] for c in cases}
        assert e_values == {"A", "B", "C"}

    def test_empty_variables(self):
        cases = _generate_test_cases({"variables": [], "nodes": []})
        assert cases == []


# ---------------------------------------------------------------------------
# Variable mapping tests
# ---------------------------------------------------------------------------


class TestBuildVariableMap:
    def test_identical_names(self):
        var_map = _build_variable_map(MINIMAL_GOLDEN, _make_extracted_perfect())
        assert var_map["var_a_bool"].extracted_id == "v_001"
        assert var_map["var_b_number"].extracted_id == "v_002"
        assert not var_map["var_a_bool"].needs_conversion
        assert not var_map["var_b_number"].needs_conversion

    def test_cross_type_number_bool_mapped(self):
        """Number↔bool cross-type pairs should map when names are similar."""
        golden = {"variables": [
            {"id": "g1", "name": "A1c After Metformin", "type": "number", "source": "input"},
        ]}
        extracted = {"variables": [
            {"id": "e1", "name": "A1c Controlled on Metformin", "type": "bool", "source": "input"},
        ]}
        var_map = _build_variable_map(golden, extracted)
        assert "g1" in var_map
        assert var_map["g1"].extracted_id == "e1"
        assert var_map["g1"].needs_conversion is True
        assert var_map["g1"].golden_type == "number"
        assert var_map["g1"].extracted_type == "bool"

    def test_cross_type_low_name_sim_excluded(self):
        """Cross-type pairs with very different names should NOT map."""
        golden = {"variables": [
            {"id": "g1", "name": "Patient Age", "type": "number", "source": "input"},
        ]}
        extracted = {"variables": [
            {"id": "e1", "name": "Has Diabetes", "type": "bool", "source": "input"},
        ]}
        var_map = _build_variable_map(golden, extracted)
        assert "g1" not in var_map

    def test_enum_number_still_excluded(self):
        """Enum↔number cross-type pairs should still be skipped."""
        golden = {"variables": [
            {"id": "g1", "name": "Score", "type": "number", "source": "input"},
        ]}
        extracted = {"variables": [
            {"id": "e1", "name": "Score", "type": "enum", "source": "input"},
        ]}
        var_map = _build_variable_map(golden, extracted)
        assert "g1" not in var_map

    def test_empty(self):
        assert _build_variable_map(EMPTY_WORKFLOW, EMPTY_WORKFLOW) == {}


class TestTranslateInputs:
    def test_translates_ids(self):
        var_map = {
            "var_a_bool": VarMapping("v_001", False, "bool", "bool"),
            "var_b_number": VarMapping("v_002", False, "number", "number"),
        }
        case = {"var_a_bool": True, "var_b_number": 15}
        translated = _translate_inputs(case, var_map, _make_extracted_perfect(), {})
        assert translated["v_001"] is True
        assert translated["v_002"] == 15

    def test_cross_type_number_to_bool(self):
        """Number→bool translation applies threshold from golden conditions."""
        var_map = {
            "g_score": VarMapping("e_controlled", True, "number", "bool"),
        }
        threshold_map = {"g_score": ThresholdInfo("lte", 48.0)}
        # 47 <= 48 → True
        translated = _translate_inputs(
            {"g_score": 47}, var_map, {}, threshold_map
        )
        assert translated["e_controlled"] is True
        # 49 <= 48 → False
        translated = _translate_inputs(
            {"g_score": 49}, var_map, {}, threshold_map
        )
        assert translated["e_controlled"] is False

    def test_extra_vars_not_in_translate(self):
        """Extra variables are NOT included in _translate_inputs — they're
        handled separately by _extra_var_combos."""
        extracted = {
            "variables": [
                {"id": "v_001", "name": "Has A", "type": "bool", "source": "input"},
                {"id": "v_extra", "name": "Extra Var", "type": "number", "source": "input"},
            ],
        }
        var_map = {"var_a_bool": VarMapping("v_001", False, "bool", "bool")}
        case = {"var_a_bool": True}
        translated = _translate_inputs(case, var_map, extracted, {})
        assert translated["v_001"] is True
        assert "v_extra" not in translated  # Handled by _extra_var_combos.


class TestExtraVarCombos:
    def test_no_extra_vars(self):
        """No extra variables → single empty combo."""
        var_map = {"g1": VarMapping("e1", False, "bool", "bool")}
        extracted = {"variables": [{"id": "e1", "name": "X", "type": "bool", "source": "input"}]}
        combos = _extra_var_combos(var_map, extracted)
        assert combos == [{}]

    def test_extra_bool(self):
        """Extra bool variable → [True, False] combos."""
        var_map = {}  # No golden vars mapped.
        extracted = {"variables": [
            {"id": "v_extra", "name": "Extra", "type": "bool", "source": "input"},
        ]}
        combos = _extra_var_combos(var_map, extracted)
        assert len(combos) == 2
        values = {c["v_extra"] for c in combos}
        assert values == {True, False}

    def test_extra_enum(self):
        """Extra enum variable → one combo per enum value."""
        var_map = {}
        extracted = {"variables": [
            {"id": "v_extra", "name": "Extra", "type": "enum", "source": "input",
             "enum_values": ["A", "B", "C"]},
        ]}
        combos = _extra_var_combos(var_map, extracted)
        assert len(combos) == 3
        values = {c["v_extra"] for c in combos}
        assert values == {"A", "B", "C"}

    def test_extra_number_uses_extracted_thresholds(self):
        """Extra number vars should use boundary values from extracted conditions."""
        var_map = {}
        extracted = {
            "variables": [
                {"id": "v_score", "name": "Score", "type": "number", "source": "input"},
            ],
            "nodes": [
                {"id": "d1", "type": "decision",
                 "condition": {"input_id": "v_score", "comparator": "gt", "value": 10}},
            ],
        }
        combos = _extra_var_combos(var_map, extracted)
        values = {c["v_score"] for c in combos}
        # Should include boundary values around threshold 10.
        assert 9.9 in values
        assert 10.0 in values
        assert 10.1 in values


# ---------------------------------------------------------------------------
# Execution tests
# ---------------------------------------------------------------------------


class TestExecuteWorkflow:
    def test_golden_executes(self):
        end_id, end_label, ok = _execute_workflow(
            MINIMAL_GOLDEN, {"var_a_bool": True, "var_b_number": 15}
        )
        assert ok is True
        assert end_id == "end_yes"
        assert end_label == "Treat with X"

    def test_false_branch(self):
        end_id, end_label, ok = _execute_workflow(
            MINIMAL_GOLDEN, {"var_a_bool": False, "var_b_number": 15}
        )
        assert ok is True
        assert end_id == "end_no"

    def test_empty_workflow(self):
        _, _, ok = _execute_workflow(EMPTY_WORKFLOW, {})
        assert ok is False

    def test_missing_variable_fails(self):
        _, _, ok = _execute_workflow(MINIMAL_GOLDEN, {"var_a_bool": True})
        assert ok is False  # Missing var_b_number.


# ---------------------------------------------------------------------------
# End node matching tests
# ---------------------------------------------------------------------------


class TestBuildEndNodeMap:
    def test_identical_labels(self):
        end_map = _build_end_node_map(MINIMAL_GOLDEN, _make_extracted_perfect())
        assert end_map == {"end_yes": "n_end_yes", "end_no": "n_end_no"}

    def test_empty_workflow(self):
        assert _build_end_node_map(EMPTY_WORKFLOW, EMPTY_WORKFLOW) == {}

    def test_greedy_1_to_1(self):
        """Each end node should be matched at most once."""
        golden = {"nodes": [
            {"id": "a", "type": "end", "label": "Refer to Specialist"},
            {"id": "b", "type": "end", "label": "Refer to Secondary Care"},
        ]}
        extracted = {"nodes": [
            {"id": "x", "type": "end", "label": "Refer to Specialist"},
            {"id": "y", "type": "end", "label": "Refer to Secondary Care"},
        ]}
        end_map = _build_end_node_map(golden, extracted)
        assert len(end_map) == 2
        assert end_map["a"] != end_map["b"]


# ---------------------------------------------------------------------------
# Full functional scoring tests
# ---------------------------------------------------------------------------


class TestFunctionalScorePerfect:
    """Perfect extraction (different IDs, same structure) → 100%."""

    def test_perfect_score(self):
        result = functional_score(MINIMAL_GOLDEN, _make_extracted_perfect())
        assert result.score == 1.0

    def test_all_cases_matched(self):
        result = functional_score(MINIMAL_GOLDEN, _make_extracted_perfect())
        assert result.cases_matched == result.cases_tested

    def test_no_failures(self):
        result = functional_score(MINIMAL_GOLDEN, _make_extracted_perfect())
        assert result.cases_golden_failed == 0
        assert result.cases_extracted_failed == 0


class TestFunctionalScoreWrongRouting:
    """Swapped branches should produce <100% but >0% (some paths still match)."""

    def test_not_perfect(self):
        result = functional_score(MINIMAL_GOLDEN, _make_extracted_wrong_routing())
        assert result.score < 1.0

    def test_some_matches(self):
        """Cases where A=False route through d2 in extracted — same as A=True in
        golden. So some cases still match by coincidence."""
        result = functional_score(MINIMAL_GOLDEN, _make_extracted_wrong_routing())
        assert result.cases_matched > 0


class TestFunctionalScoreEmpty:
    """Empty extraction → 0%."""

    def test_empty_extraction(self):
        result = functional_score(MINIMAL_GOLDEN, EMPTY_WORKFLOW)
        # All cases should fail because extracted can't execute.
        assert result.score == 0.0
        assert result.cases_extracted_failed == result.cases_tested


class TestFunctionalScoreSelfScore:
    """Scoring a workflow against itself → 100%."""

    def test_self_score(self):
        result = functional_score(MINIMAL_GOLDEN, MINIMAL_GOLDEN)
        assert result.score == 1.0


# ---------------------------------------------------------------------------
# Sanity check on real golden files
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures"


@pytest.mark.parametrize("name", ["diabetes_treatment", "lipid_management", "liver_pathology"])
def test_golden_self_score_functional(name):
    """A golden solution scored against itself should get 100%."""
    golden_path = _FIXTURES_DIR / f"golden_{name}.json"
    if not golden_path.exists():
        pytest.skip(f"Golden file not found: {golden_path}")
    golden = json.loads(golden_path.read_text())
    result = functional_score(golden, golden)
    assert result.score == 1.0, (
        f"{name}: functional self-score should be 1.0, got {result.score:.3f}"
    )
    assert result.cases_golden_failed == 0
