"""Unit tests for eval/scorer.py — the 5-dimension scoring module."""

import json
from pathlib import Path

import pytest

from eval.scorer import (
    DimensionScore,
    ScoreResult,
    _build_node_map,
    _fuzzy_ratio,
    _normalize,
    _values_match,
    score,
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
        {"id": "start", "type": "start", "label": "Start Workflow", "x": 0, "y": 0},
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
    """Return an extraction that's a perfect (relabelled-ID) match."""
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


EMPTY_WORKFLOW = {"variables": [], "nodes": [], "edges": [], "outputs": []}


# ---------------------------------------------------------------------------
# Fuzzy matching tests
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_basic(self):
        assert _normalize("Hello World!") == "hello world"

    def test_special_chars(self):
        assert _normalize("A1c > 58?") == "a1c  58"

    def test_empty(self):
        assert _normalize("") == ""


class TestFuzzyRatio:
    def test_identical(self):
        assert _fuzzy_ratio("Hello", "Hello") == 1.0

    def test_case_insensitive(self):
        assert _fuzzy_ratio("Hello World", "hello world") == 1.0

    def test_similar(self):
        ratio = _fuzzy_ratio(
            "Tests Normalise or Notably Improve?",
            "Tests normalise or notably improve?",
        )
        assert ratio == 1.0  # identical after normalization

    def test_different(self):
        ratio = _fuzzy_ratio("Completely different text", "Foo bar baz")
        assert ratio < 0.5


class TestValuesMatch:
    def test_both_none(self):
        assert _values_match(None, None) is True

    def test_one_none(self):
        assert _values_match(10, None) is False

    def test_exact_int(self):
        assert _values_match(10, 10) is True

    def test_within_tolerance(self):
        # 2.67 vs 2.7 → 1.1% difference, within 5%.
        assert _values_match(2.67, 2.7) is True

    def test_outside_tolerance(self):
        assert _values_match(10, 12) is False

    def test_string_match(self):
        assert _values_match("Primary", "primary") is True


# ---------------------------------------------------------------------------
# Node mapping tests
# ---------------------------------------------------------------------------


class TestBuildNodeMap:
    def test_perfect_match(self):
        """Identical labels should map 1:1."""
        g_nodes = [
            {"id": "a", "type": "start", "label": "Start"},
            {"id": "b", "type": "decision", "label": "Check Something"},
        ]
        e_nodes = [
            {"id": "x", "type": "start", "label": "Start"},
            {"id": "y", "type": "decision", "label": "Check Something"},
        ]
        node_map = _build_node_map(g_nodes, e_nodes)
        assert node_map == {"a": "x", "b": "y"}

    def test_fuzzy_match(self):
        """Similar labels should still match."""
        g_nodes = [{"id": "a", "type": "decision", "label": "FIB-4 > 2.67? (High Risk)"}]
        e_nodes = [{"id": "x", "type": "decision", "label": "FIB-4 Score > 2.67? (High Risk at any age)"}]
        node_map = _build_node_map(g_nodes, e_nodes)
        assert "a" in node_map

    def test_no_double_match(self):
        """Greedy 1:1 — each extracted node used at most once."""
        g_nodes = [
            {"id": "a", "type": "end", "label": "Refer to Specialist"},
            {"id": "b", "type": "end", "label": "Refer to Secondary Care"},
        ]
        e_nodes = [
            {"id": "x", "type": "end", "label": "Refer to Specialist"},
            {"id": "y", "type": "end", "label": "Refer to Secondary Care"},
        ]
        node_map = _build_node_map(g_nodes, e_nodes)
        # Both should be mapped, to different targets.
        assert len(node_map) == 2
        assert node_map["a"] != node_map["b"]

    def test_below_threshold(self):
        """Completely different labels should not match."""
        g_nodes = [{"id": "a", "type": "start", "label": "Alpha Beta Gamma"}]
        e_nodes = [{"id": "x", "type": "start", "label": "Foo Bar Baz Quux"}]
        node_map = _build_node_map(g_nodes, e_nodes)
        assert "a" not in node_map


# ---------------------------------------------------------------------------
# Full scoring tests
# ---------------------------------------------------------------------------


class TestScorePerfectMatch:
    """Perfect extraction (different IDs, same labels) → ~1.0 everywhere."""

    def test_overall_near_perfect(self):
        result = score(MINIMAL_GOLDEN, _make_extracted_perfect())
        assert result.overall >= 0.95

    def test_variables_perfect(self):
        result = score(MINIMAL_GOLDEN, _make_extracted_perfect())
        assert result.variables.score == 1.0

    def test_nodes_perfect(self):
        result = score(MINIMAL_GOLDEN, _make_extracted_perfect())
        assert result.nodes.score == 1.0

    def test_topology_perfect(self):
        result = score(MINIMAL_GOLDEN, _make_extracted_perfect())
        assert result.topology.score == 1.0

    def test_conditions_perfect(self):
        result = score(MINIMAL_GOLDEN, _make_extracted_perfect())
        assert result.conditions.score == pytest.approx(1.0)

    def test_outputs_perfect(self):
        result = score(MINIMAL_GOLDEN, _make_extracted_perfect())
        assert result.outputs.score == 1.0


class TestScoreEmptyExtraction:
    """Empty extraction → 0.0 everywhere."""

    def test_overall_zero(self):
        result = score(MINIMAL_GOLDEN, EMPTY_WORKFLOW)
        assert result.overall == 0.0

    def test_all_dimensions_zero(self):
        result = score(MINIMAL_GOLDEN, EMPTY_WORKFLOW)
        assert result.variables.score == 0.0
        assert result.nodes.score == 0.0
        assert result.topology.score == 0.0
        assert result.conditions.score == 0.0
        assert result.outputs.score == 0.0


class TestTopologyCascade:
    """Unmapping one node should cause all edges touching it to fail."""

    def test_missing_node_kills_its_edges(self):
        # Extract without d2 — edges involving d2 should fail.
        extracted = {
            "variables": [],
            "nodes": [
                {"id": "n_start", "type": "start", "label": "Start Workflow"},
                {"id": "n_d1", "type": "decision", "label": "Has Condition A?",
                 "condition": {"input_id": "v_001", "comparator": "is_true"}},
                # d2 missing
                {"id": "n_end_yes", "type": "end", "label": "Treat with X",
                 "output_value": "Treat with X"},
                {"id": "n_end_no", "type": "end", "label": "No Treatment",
                 "output_value": "No Treatment"},
            ],
            "edges": [
                {"from": "n_start", "to": "n_d1", "label": ""},
                {"from": "n_d1", "to": "n_end_no", "label": "false"},
            ],
            "outputs": [],
        }
        result = score(MINIMAL_GOLDEN, extracted)
        # d2 unmapped → edges d1->d2, d2->end_yes, d2->end_no all fail.
        # Only start->d1 and d1->end_no can match = 2 out of 5.
        assert result.topology.score < 0.6
        assert result.topology.matched <= 2


class TestConditionScoring:
    def test_wrong_comparator(self):
        """Wrong comparator should lose comparator points but keep has_condition."""
        extracted = _make_extracted_perfect()
        # Change comparator on d2 from "gt" to "gte".
        extracted["nodes"][2]["condition"]["comparator"] = "gte"
        result = score(MINIMAL_GOLDEN, extracted)
        # One of two conditions has wrong comparator → not perfect.
        assert result.conditions.score < 1.0
        assert result.conditions.score > 0.5

    def test_wrong_value(self):
        """Wrong numeric value (outside 5% tolerance) should lose value points."""
        extracted = _make_extracted_perfect()
        # Change value from 10 to 20 (100% off).
        extracted["nodes"][2]["condition"]["value"] = 20
        result = score(MINIMAL_GOLDEN, extracted)
        assert result.conditions.score < 1.0


class TestScoreResult:
    def test_summary_dict_keys(self):
        result = score(MINIMAL_GOLDEN, _make_extracted_perfect())
        d = result.summary_dict()
        expected_keys = {
            "score_overall", "score_variables", "score_nodes",
            "score_topology", "score_conditions", "score_outputs",
            "score_functional",
        }
        assert set(d.keys()) == expected_keys

    def test_summary_dict_values_are_rounded(self):
        result = score(MINIMAL_GOLDEN, _make_extracted_perfect())
        d = result.summary_dict()
        for v in d.values():
            # All values should be rounded to 3 decimal places.
            assert isinstance(v, float)
            assert v == round(v, 3)


# ---------------------------------------------------------------------------
# Sanity check on real golden files
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures"


@pytest.mark.parametrize("name", ["diabetes_treatment", "lipid_management", "liver_pathology"])
def test_golden_scores_itself_perfectly(name):
    """A golden solution scored against itself should get ~1.0."""
    golden_path = _FIXTURES_DIR / f"golden_{name}.json"
    if not golden_path.exists():
        pytest.skip(f"Golden file not found: {golden_path}")
    golden = json.loads(golden_path.read_text())
    result = score(golden, golden)
    assert result.overall >= 0.95, (
        f"{name}: self-score should be ~1.0, got {result.overall:.3f}"
    )
