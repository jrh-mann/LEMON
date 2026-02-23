from __future__ import annotations

from typing import Any, Dict, List

from evals.scoring import normalize_branch_label, normalize_label, score_trial


class _DummyGroundTruth:
    TEST_CASES = [
        {"inputs": {"age": 20}, "expected_output": "Adult"},
        {"inputs": {"age": 16}, "expected_output": "Minor"},
    ]

    @staticmethod
    def determine_workflow_outcome(inputs: Dict[str, Any]) -> str:
        return "Adult" if int(inputs.get("age", 0)) >= 18 else "Minor"


def _base_case_config() -> Dict[str, Any]:
    return {
        "case_id": "dummy",
        "canonical_expected_nodes": [
            {"id": "start", "type": "start", "label": "Start"},
            {"id": "age_check", "type": "decision", "label": "Age >= 18"},
            {"id": "out_adult", "type": "end", "label": "Adult"},
            {"id": "out_minor", "type": "end", "label": "Minor"},
        ],
        "canonical_expected_edges": [
            {"from": "start", "to": "age_check", "label": ""},
            {"from": "age_check", "to": "out_adult", "label": "true"},
            {"from": "age_check", "to": "out_minor", "label": "false"},
        ],
        "expected_variables": [{"name": "age", "type": "int"}],
        "expected_outputs": ["Adult", "Minor"],
    }


def _base_analysis_and_flowchart() -> tuple[Dict[str, Any], Dict[str, Any]]:
    analysis = {
        "variables": [
            {
                "id": "input_age_int",
                "name": "age",
                "type": "int",
                "source": "input",
                "range": {"min": 0, "max": 120},
            }
        ],
        "outputs": [{"name": "Adult"}, {"name": "Minor"}],
        "tree": {
            "start": {
                "id": "start",
                "type": "start",
                "label": "Start",
                "children": [
                    {
                        "id": "age_check",
                        "type": "decision",
                        "label": "Age >= 18",
                        "condition": {
                            "input_id": "input_age_int",
                            "comparator": "gte",
                            "value": 18,
                        },
                        "children": [
                            {
                                "id": "out_adult",
                                "type": "output",
                                "label": "Adult",
                                "edge_label": "true",
                                "children": [],
                            },
                            {
                                "id": "out_minor",
                                "type": "output",
                                "label": "Minor",
                                "edge_label": "false",
                                "children": [],
                            },
                        ],
                    }
                ],
            }
        },
        "doubts": [],
    }
    flowchart = {
        "nodes": [
            {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
            {"id": "age_check", "type": "decision", "label": "Age >= 18", "x": 0, "y": 0},
            {"id": "out_adult", "type": "end", "label": "Adult", "x": 0, "y": 0},
            {"id": "out_minor", "type": "end", "label": "Minor", "x": 0, "y": 0},
        ],
        "edges": [
            {"from": "start", "to": "age_check", "label": ""},
            {"from": "age_check", "to": "out_adult", "label": "Yes"},
            {"from": "age_check", "to": "out_minor", "label": "No"},
        ],
    }
    return analysis, flowchart


def test_label_normalization():
    assert normalize_label("  A1c <= 58  ") == "a1c  58"
    assert normalize_branch_label("YES") == "true"
    assert normalize_branch_label("no") == "false"


def test_edge_matching_with_yes_no_normalization():
    case = _base_case_config()
    analysis, flowchart = _base_analysis_and_flowchart()

    result = score_trial(case, analysis, flowchart, _DummyGroundTruth)

    assert result["metrics"]["edge_f1"] == 1.0
    assert result["metrics"]["node_f1"] == 1.0


def test_variable_and_output_scoring_penalizes_mismatch():
    case = _base_case_config()
    analysis, flowchart = _base_analysis_and_flowchart()

    analysis["variables"] = [
        {
            "id": "input_height_int",
            "name": "height",
            "type": "int",
            "source": "input",
        }
    ]
    analysis["outputs"] = [{"name": "Adult"}]

    result = score_trial(case, analysis, flowchart, _DummyGroundTruth)

    assert result["metrics"]["variable_f1"] == 0.0
    assert result["metrics"]["output_f1"] < 1.0


def test_composite_score_is_deterministic_weighted_sum():
    case = _base_case_config()
    analysis, flowchart = _base_analysis_and_flowchart()
    result = score_trial(case, analysis, flowchart, _DummyGroundTruth)

    metrics = result["metrics"]
    expected = (
        0.25 * metrics["node_f1"]
        + 0.25 * metrics["edge_f1"]
        + 0.15 * metrics["variable_f1"]
        + 0.10 * metrics["output_f1"]
        + 0.20 * metrics["semantic_score"]
        + 0.05 * metrics["validity_score"]
    )

    assert abs(result["composite_raw"] - expected) < 1e-9
    assert result["composite_score"] == round(expected * 100.0, 2)
