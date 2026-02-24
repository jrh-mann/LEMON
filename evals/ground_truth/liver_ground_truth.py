"""Ground-truth logic for ``Liver Pathology .png``."""

from __future__ import annotations

from typing import Any, Dict, List


INPUT_SCHEMA = [
    {"name": "months_with_abnormal_lfts", "type": "int"},
    {"name": "tests_normalise_or_notably_improve", "type": "bool"},
    {"name": "sustained_or_worsening_abnormalities", "type": "bool"},
    {"name": "fib4_score", "type": "float"},
    {"name": "nafld_fibrosis_score", "type": "float"},
    {"name": "age", "type": "int"},
    {"name": "fibroscan_available", "type": "bool"},
    {"name": "fibroscan_high_risk", "type": "bool"},
    {"name": "rare_conditions_suspected", "type": "bool"},
    {"name": "liver_uss_done_since_abnormal_lft", "type": "bool"},
    {"name": "raised_igg", "type": "bool"},
    {"name": "ulcerative_colitis_or_panca_positive", "type": "bool"},
    {"name": "no_concern_after_review", "type": "bool"},
]

POSSIBLE_OUTPUTS = [
    "Mark as Normal / Satisfactory",
    "Recheck Baseline Liver Profile in appropriate timeframe",
    "Manage risk factors and co-morbidities - Annual Screening",
    "Fibroscan if available",
    "Phase 4 Bloods",
    "Refer to Secondary Care once bloods are back, irrespective of diagnosis or if all tests normal",
    "No Concern, or escalation required",
]

TEST_CASES: List[Dict[str, Any]] = [
    {
        "inputs": {
            "months_with_abnormal_lfts": 4,
            "tests_normalise_or_notably_improve": True,
            "sustained_or_worsening_abnormalities": False,
            "fib4_score": 0.9,
            "nafld_fibrosis_score": -2.0,
            "age": 45,
            "fibroscan_available": False,
            "fibroscan_high_risk": False,
            "rare_conditions_suspected": False,
            "liver_uss_done_since_abnormal_lft": True,
            "raised_igg": False,
            "ulcerative_colitis_or_panca_positive": False,
            "no_concern_after_review": False,
        },
        "expected_output": "Mark as Normal / Satisfactory",
    },
    {
        "inputs": {
            "months_with_abnormal_lfts": 1,
            "tests_normalise_or_notably_improve": False,
            "sustained_or_worsening_abnormalities": False,
            "fib4_score": 1.0,
            "nafld_fibrosis_score": -1.8,
            "age": 40,
            "fibroscan_available": False,
            "fibroscan_high_risk": False,
            "rare_conditions_suspected": False,
            "liver_uss_done_since_abnormal_lft": True,
            "raised_igg": False,
            "ulcerative_colitis_or_panca_positive": False,
            "no_concern_after_review": False,
        },
        "expected_output": "Recheck Baseline Liver Profile in appropriate timeframe",
    },
    {
        "inputs": {
            "months_with_abnormal_lfts": 6,
            "tests_normalise_or_notably_improve": False,
            "sustained_or_worsening_abnormalities": True,
            "fib4_score": 1.0,
            "nafld_fibrosis_score": -2.0,
            "age": 50,
            "fibroscan_available": False,
            "fibroscan_high_risk": False,
            "rare_conditions_suspected": False,
            "liver_uss_done_since_abnormal_lft": True,
            "raised_igg": False,
            "ulcerative_colitis_or_panca_positive": False,
            "no_concern_after_review": False,
        },
        "expected_output": "Manage risk factors and co-morbidities - Annual Screening",
    },
    {
        "inputs": {
            "months_with_abnormal_lfts": 6,
            "tests_normalise_or_notably_improve": False,
            "sustained_or_worsening_abnormalities": True,
            "fib4_score": 3.0,
            "nafld_fibrosis_score": 0.8,
            "age": 68,
            "fibroscan_available": False,
            "fibroscan_high_risk": False,
            "rare_conditions_suspected": False,
            "liver_uss_done_since_abnormal_lft": True,
            "raised_igg": False,
            "ulcerative_colitis_or_panca_positive": False,
            "no_concern_after_review": False,
        },
        "expected_output": "Refer to Secondary Care once bloods are back, irrespective of diagnosis or if all tests normal",
    },
    {
        "inputs": {
            "months_with_abnormal_lfts": 6,
            "tests_normalise_or_notably_improve": False,
            "sustained_or_worsening_abnormalities": True,
            "fib4_score": 1.9,
            "nafld_fibrosis_score": 0.0,
            "age": 70,
            "fibroscan_available": False,
            "fibroscan_high_risk": False,
            "rare_conditions_suspected": False,
            "liver_uss_done_since_abnormal_lft": True,
            "raised_igg": False,
            "ulcerative_colitis_or_panca_positive": False,
            "no_concern_after_review": False,
        },
        "expected_output": "Fibroscan if available",
    },
    {
        "inputs": {
            "months_with_abnormal_lfts": 6,
            "tests_normalise_or_notably_improve": False,
            "sustained_or_worsening_abnormalities": True,
            "fib4_score": 1.9,
            "nafld_fibrosis_score": 0.0,
            "age": 70,
            "fibroscan_available": True,
            "fibroscan_high_risk": False,
            "rare_conditions_suspected": True,
            "liver_uss_done_since_abnormal_lft": False,
            "raised_igg": True,
            "ulcerative_colitis_or_panca_positive": True,
            "no_concern_after_review": False,
        },
        "expected_output": "Phase 4 Bloods",
    },
    {
        "inputs": {
            "months_with_abnormal_lfts": 6,
            "tests_normalise_or_notably_improve": False,
            "sustained_or_worsening_abnormalities": True,
            "fib4_score": 1.9,
            "nafld_fibrosis_score": 0.0,
            "age": 70,
            "fibroscan_available": True,
            "fibroscan_high_risk": True,
            "rare_conditions_suspected": False,
            "liver_uss_done_since_abnormal_lft": True,
            "raised_igg": False,
            "ulcerative_colitis_or_panca_positive": False,
            "no_concern_after_review": False,
        },
        "expected_output": "Refer to Secondary Care once bloods are back, irrespective of diagnosis or if all tests normal",
    },
    {
        "inputs": {
            "months_with_abnormal_lfts": 6,
            "tests_normalise_or_notably_improve": False,
            "sustained_or_worsening_abnormalities": True,
            "fib4_score": 1.0,
            "nafld_fibrosis_score": -2.0,
            "age": 50,
            "fibroscan_available": False,
            "fibroscan_high_risk": False,
            "rare_conditions_suspected": False,
            "liver_uss_done_since_abnormal_lft": True,
            "raised_igg": False,
            "ulcerative_colitis_or_panca_positive": False,
            "no_concern_after_review": True,
        },
        "expected_output": "No Concern, or escalation required",
    },
]


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _fib4_category(score: float, age: int) -> str:
    if score > 2.67:
        return "high"
    low_threshold = 2.0 if age > 65 else 1.3
    if score < low_threshold:
        return "low"
    return "intermediate"


def _nafld_category(score: float) -> str:
    if score < -1.455:
        return "low"
    if score > 0.675:
        return "high"
    return "indeterminate"


def determine_workflow_outcome(inputs: Dict[str, Any]) -> str:
    months_with_abnormal_lfts = _as_int(inputs.get("months_with_abnormal_lfts"))
    tests_normalise = _as_bool(inputs.get("tests_normalise_or_notably_improve"))
    sustained_or_worsening = _as_bool(inputs.get("sustained_or_worsening_abnormalities"))

    if tests_normalise:
        return "Mark as Normal / Satisfactory"

    if months_with_abnormal_lfts < 3 and not sustained_or_worsening:
        return "Recheck Baseline Liver Profile in appropriate timeframe"

    fib4_score = _as_float(inputs.get("fib4_score"))
    nafld_score = _as_float(inputs.get("nafld_fibrosis_score"))
    age = _as_int(inputs.get("age"))

    fib4_cat = _fib4_category(fib4_score, age)
    nafld_cat = _nafld_category(nafld_score)

    if fib4_cat == "high" or nafld_cat == "high":
        primary = "Refer to Secondary Care once bloods are back, irrespective of diagnosis or if all tests normal"
    elif fib4_cat == "low" and nafld_cat == "low":
        primary = "Manage risk factors and co-morbidities - Annual Screening"
    elif _as_bool(inputs.get("fibroscan_available")):
        if _as_bool(inputs.get("fibroscan_high_risk")):
            primary = "Refer to Secondary Care once bloods are back, irrespective of diagnosis or if all tests normal"
        else:
            primary = "Phase 4 Bloods"
    else:
        primary = "Fibroscan if available"

    if _as_bool(inputs.get("no_concern_after_review")) and "Refer to Secondary Care" not in primary:
        primary = "No Concern, or escalation required"

    return primary
