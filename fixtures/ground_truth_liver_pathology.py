"""Ground-truth logic for `Liver Pathology .png` (phased work-up flow).

The chart is broad and includes advisory boxes; this script encodes the
deterministic triage/risk-routing decisions into a single recommendation.
"""

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
    """Approximate FIB-4 chart logic from the image."""
    if score > 2.67:
        return "high"
    # Age-adjusted low-risk threshold seen in the chart.
    low_threshold = 2.0 if age > 65 else 1.3
    if score < low_threshold:
        return "low"
    return "intermediate"


def _nafld_category(score: float) -> str:
    """NAFLD fibrosis score category thresholds from the chart."""
    if score < -1.455:
        return "low"
    if score > 0.675:
        return "high"
    return "indeterminate"


def determine_workflow_outcome(inputs: Dict[str, Any]) -> str:
    """Return the primary next-step recommendation for liver pathology work-up."""
    months_with_abnormal_lfts = _as_int(inputs.get("months_with_abnormal_lfts"))
    tests_normalise = _as_bool(inputs.get("tests_normalise_or_notably_improve"))
    sustained_or_worsening = _as_bool(inputs.get("sustained_or_worsening_abnormalities"))

    # Early exit branch from top-right pathway.
    if tests_normalise:
        return "Mark as Normal / Satisfactory"

    # Recheck branch when abnormality window is not yet long enough.
    if months_with_abnormal_lfts < 3 and not sustained_or_worsening:
        return "Recheck Baseline Liver Profile in appropriate timeframe"

    fib4_score = _as_float(inputs.get("fib4_score"))
    nafld_score = _as_float(inputs.get("nafld_fibrosis_score"))
    age = _as_int(inputs.get("age"))

    fib4_cat = _fib4_category(fib4_score, age)
    nafld_cat = _nafld_category(nafld_score)

    if fib4_cat == "high" or nafld_cat == "high":
        primary = (
            "Refer to Secondary Care once bloods are back, irrespective of diagnosis or if all tests normal"
        )
    elif fib4_cat == "low" and nafld_cat == "low":
        primary = "Manage risk factors and co-morbidities - Annual Screening"
    elif _as_bool(inputs.get("fibroscan_available")):
        if _as_bool(inputs.get("fibroscan_high_risk")):
            primary = (
                "Refer to Secondary Care once bloods are back, irrespective of diagnosis or if all tests normal"
            )
        else:
            primary = "Phase 4 Bloods"
    else:
        primary = "Fibroscan if available"

    if _as_bool(inputs.get("no_concern_after_review")) and "Refer to Secondary Care" not in primary:
        primary = "No Concern, or escalation required"

    additional_actions: List[str] = []
    additional_actions.append("Patient needs consultation for liver pathology and consent for further testing")

    if not _as_bool(inputs.get("liver_uss_done_since_abnormal_lft"), default=True):
        additional_actions.append("Request Liver USS if not done since abnormal LFT have been noted")
    if _as_bool(inputs.get("rare_conditions_suspected")):
        additional_actions.append("Additional tests should be done for rare conditions")
    if _as_bool(inputs.get("ulcerative_colitis_or_panca_positive")):
        additional_actions.append("Requires MRCP via Gastroenterology")
    if _as_bool(inputs.get("raised_igg")):
        additional_actions.append("Autoimmune Hepatitis Type 1/2 Screen")

    if additional_actions and "Refer to Secondary Care" not in primary:
        return f"{primary} | Additional actions: {'; '.join(additional_actions)}"
    return primary

