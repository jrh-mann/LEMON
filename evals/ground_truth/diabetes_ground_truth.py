"""Ground-truth treatment logic for ``Diabetes Treatment .png``.

Expanded with explicit subworkflow derivation helpers to avoid relying on
single flat booleans for top-level routing decisions.
"""

from __future__ import annotations

from typing import Any, Dict, List


INPUT_SCHEMA = [
    {"name": "symptoms_and_new_a1c_gt_58", "type": "bool"},
    {"name": "symptoms_present", "type": "bool"},
    {"name": "new_a1c", "type": "float"},
    {"name": "admission_required", "type": "bool"},
    {"name": "cvd_known_or_risk", "type": "bool"},
    {"name": "heart_failure", "type": "bool"},
    {"name": "ckd", "type": "bool"},
    {"name": "ihd", "type": "bool"},
    {"name": "qrisk_gt_10", "type": "bool"},
    {"name": "age", "type": "int"},
    {"name": "hypertension", "type": "bool"},
    {"name": "high_lipids", "type": "bool"},
    {"name": "smoking", "type": "bool"},
    {"name": "bmi", "type": "float"},
    {"name": "fhx_cvd", "type": "bool"},
    {"name": "metformin_tolerated", "type": "bool"},
    {"name": "a1c_after_metformin", "type": "float"},
    {"name": "a1c_after_sglt2i", "type": "float"},
    {"name": "a1c_after_dual_therapy", "type": "float"},
    {"name": "a1c_after_triple_therapy", "type": "float"},
    {"name": "a1c_after_glp", "type": "float"},
    {"name": "dual_agent_choice", "type": "string"},
    {"name": "high_prognostic_value", "type": "bool"},
    {"name": "established_cvd", "type": "bool"},
    {"name": "known_ckd", "type": "bool"},
]

POSSIBLE_OUTPUTS = [
    "Admit via A&E/Medics",
    "Start Gliclazide or Insulin",
    "Metformin (continue and review in 3 months)",
    "SGLT2i (continue and review in 3 months)",
    "Ozempic titrate to full dose with 3 monthly A1c's",
    "Metformin + Gliptin/Pioglitazone/Gliclazide (consider SGLT2i)",
    "Metformin + Gliptin",
    "Metformin + Pioglitazone",
    "Metformin + Gliclazide",
    "Ozempic",
    "Mounjaro",
    "Refer to Insulin Initiator",
]


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on", "high"}
    return default


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def derive_symptoms_and_new_a1c_gt_58(inputs: Dict[str, Any]) -> bool:
    if "symptoms_and_new_a1c_gt_58" in inputs:
        return _as_bool(inputs.get("symptoms_and_new_a1c_gt_58"))

    symptoms_present = _as_bool(inputs.get("symptoms_present"))
    new_a1c = _as_float(inputs.get("new_a1c"))
    if new_a1c is None:
        return False
    return symptoms_present and new_a1c > 58.0


def derive_cvd_known_or_risk(inputs: Dict[str, Any]) -> bool:
    if "cvd_known_or_risk" in inputs:
        return _as_bool(inputs.get("cvd_known_or_risk"))

    known_bucket = any(
        _as_bool(inputs.get(key))
        for key in ("heart_failure", "ckd", "ihd", "established_cvd", "known_ckd")
    )
    if known_bucket:
        return True

    age = _as_int(inputs.get("age"), 99)
    risk_bucket = _as_bool(inputs.get("qrisk_gt_10"))
    under_40_risk = age < 40 and any(
        _as_bool(inputs.get(key))
        for key in ("hypertension", "high_lipids", "smoking", "fhx_cvd")
    )
    bmi = _as_float(inputs.get("bmi")) or 0.0
    return risk_bucket or under_40_risk or bmi > 25.0


def derive_high_prognostic_value(inputs: Dict[str, Any]) -> bool:
    if "high_prognostic_value" in inputs:
        return _as_bool(inputs.get("high_prognostic_value"))

    any_red_box = derive_cvd_known_or_risk(inputs)
    established_cvd = _as_bool(inputs.get("established_cvd"))
    known_ckd = _as_bool(inputs.get("known_ckd")) or _as_bool(inputs.get("ckd"))
    return any_red_box or established_cvd or known_ckd


def _a1c_controlled(stage_a1c: float | None, threshold: float) -> bool:
    return stage_a1c is not None and stage_a1c <= threshold


def _normalise_dual_agent(raw: Any) -> str:
    choice = str(raw or "").strip().lower()
    if choice in {"gliptin", "pioglitazone", "gliclazide"}:
        return choice
    return "gliptin"


def determine_workflow_outcome(inputs: Dict[str, Any]) -> str:
    """Return the next recommended action for the diabetes treatment algorithm."""
    symptoms_and_new_a1c_gt_58 = derive_symptoms_and_new_a1c_gt_58(inputs)
    admission_required = _as_bool(inputs.get("admission_required"))

    if symptoms_and_new_a1c_gt_58:
        if admission_required:
            return "Admit via A&E/Medics"
        return "Start Gliclazide or Insulin"

    cvd_known_or_risk = derive_cvd_known_or_risk(inputs)
    metformin_tolerated = _as_bool(inputs.get("metformin_tolerated"), default=True)

    a1c_after_metformin = _as_float(inputs.get("a1c_after_metformin"))
    a1c_after_sglt2i = _as_float(inputs.get("a1c_after_sglt2i"))
    a1c_after_dual = _as_float(inputs.get("a1c_after_dual_therapy"))
    a1c_after_triple = _as_float(inputs.get("a1c_after_triple_therapy"))
    a1c_after_glp = _as_float(inputs.get("a1c_after_glp"))

    controlled_metformin = _a1c_controlled(a1c_after_metformin, 48.0)
    controlled_sglt2i = _a1c_controlled(a1c_after_sglt2i, 53.0)
    controlled_dual = _a1c_controlled(a1c_after_dual, 53.0)
    controlled_triple = _a1c_controlled(a1c_after_triple, 58.0)
    controlled_glp = _a1c_controlled(a1c_after_glp, 58.0)

    if cvd_known_or_risk:
        if controlled_metformin:
            return "Metformin (continue and review in 3 months)"

        if metformin_tolerated and controlled_sglt2i:
            return "SGLT2i (continue and review in 3 months)"
        if not metformin_tolerated and controlled_sglt2i:
            return "SGLT2i (continue and review in 3 months)"

        if controlled_glp:
            return "Ozempic titrate to full dose with 3 monthly A1c's"
        return "Refer to Insulin Initiator"

    if controlled_metformin:
        return "Metformin (continue and review in 3 months)"

    dual_choice = _normalise_dual_agent(inputs.get("dual_agent_choice"))
    if controlled_dual:
        return f"Metformin + {dual_choice.title()}"

    if controlled_triple:
        return "Metformin + Gliptin/Pioglitazone/Gliclazide (consider SGLT2i)"

    bmi = _as_float(inputs.get("bmi")) or 0.0
    if bmi < 23.0:
        return "Metformin + Gliptin/Pioglitazone/Gliclazide (consider SGLT2i)"

    if controlled_glp:
        if derive_high_prognostic_value(inputs):
            return "Ozempic"
        return "Mounjaro"

    return "Refer to Insulin Initiator"


TEST_CASES: List[Dict[str, Any]] = [
    {
        "inputs": {
            "symptoms_present": True,
            "new_a1c": 62.0,
            "admission_required": True,
            "heart_failure": True,
            "a1c_after_metformin": 62.0,
            "a1c_after_sglt2i": 60.0,
            "a1c_after_dual_therapy": 61.0,
            "a1c_after_triple_therapy": 60.0,
            "a1c_after_glp": 59.0,
            "dual_agent_choice": "gliptin",
            "bmi": 30.0,
        },
        "expected_output": "Admit via A&E/Medics",
    },
    {
        "inputs": {
            "symptoms_present": True,
            "new_a1c": 63.0,
            "admission_required": False,
            "a1c_after_metformin": 62.0,
            "a1c_after_sglt2i": 60.0,
            "a1c_after_dual_therapy": 61.0,
            "a1c_after_triple_therapy": 60.0,
            "a1c_after_glp": 59.0,
            "dual_agent_choice": "gliptin",
            "bmi": 30.0,
        },
        "expected_output": "Start Gliclazide or Insulin",
    },
    {
        "inputs": {
            "symptoms_present": False,
            "new_a1c": 54.0,
            "heart_failure": True,
            "a1c_after_metformin": 47.0,
            "a1c_after_sglt2i": 52.0,
            "a1c_after_dual_therapy": 54.0,
            "a1c_after_triple_therapy": 57.0,
            "a1c_after_glp": 56.0,
            "dual_agent_choice": "gliptin",
            "bmi": 29.0,
        },
        "expected_output": "Metformin (continue and review in 3 months)",
    },
    {
        "inputs": {
            "symptoms_present": False,
            "new_a1c": 54.0,
            "heart_failure": True,
            "metformin_tolerated": True,
            "a1c_after_metformin": 55.0,
            "a1c_after_sglt2i": 52.0,
            "a1c_after_dual_therapy": 58.0,
            "a1c_after_triple_therapy": 59.0,
            "a1c_after_glp": 59.0,
            "dual_agent_choice": "gliptin",
            "bmi": 29.0,
        },
        "expected_output": "SGLT2i (continue and review in 3 months)",
    },
    {
        "inputs": {
            "symptoms_present": False,
            "new_a1c": 55.0,
            "heart_failure": True,
            "metformin_tolerated": False,
            "a1c_after_metformin": 58.0,
            "a1c_after_sglt2i": 54.0,
            "a1c_after_dual_therapy": 59.0,
            "a1c_after_triple_therapy": 59.0,
            "a1c_after_glp": 57.0,
            "dual_agent_choice": "gliptin",
            "bmi": 31.0,
        },
        "expected_output": "Ozempic titrate to full dose with 3 monthly A1c's",
    },
    {
        "inputs": {
            "symptoms_present": False,
            "new_a1c": 57.0,
            "age": 36,
            "hypertension": True,
            "smoking": True,
            "a1c_after_metformin": 60.0,
            "a1c_after_sglt2i": 58.0,
            "a1c_after_dual_therapy": 58.0,
            "a1c_after_triple_therapy": 59.0,
            "a1c_after_glp": 60.0,
            "dual_agent_choice": "gliptin",
            "bmi": 31.0,
        },
        "expected_output": "Refer to Insulin Initiator",
    },
    {
        "inputs": {
            "symptoms_present": False,
            "new_a1c": 54.0,
            "cvd_known_or_risk": False,
            "a1c_after_metformin": 54.0,
            "a1c_after_sglt2i": 57.0,
            "a1c_after_dual_therapy": 52.0,
            "a1c_after_triple_therapy": 58.0,
            "a1c_after_glp": 58.0,
            "dual_agent_choice": "gliclazide",
            "bmi": 27.0,
        },
        "expected_output": "Metformin + Gliclazide",
    },
    {
        "inputs": {
            "symptoms_present": False,
            "new_a1c": 55.0,
            "cvd_known_or_risk": False,
            "a1c_after_metformin": 55.0,
            "a1c_after_sglt2i": 57.0,
            "a1c_after_dual_therapy": 56.0,
            "a1c_after_triple_therapy": 59.0,
            "a1c_after_glp": 57.0,
            "dual_agent_choice": "gliptin",
            "bmi": 30.0,
            "established_cvd": True,
        },
        "expected_output": "Ozempic",
    },
    {
        "inputs": {
            "symptoms_present": False,
            "new_a1c": 55.0,
            "cvd_known_or_risk": False,
            "a1c_after_metformin": 55.0,
            "a1c_after_sglt2i": 57.0,
            "a1c_after_dual_therapy": 56.0,
            "a1c_after_triple_therapy": 59.0,
            "a1c_after_glp": 57.0,
            "dual_agent_choice": "gliptin",
            "bmi": 30.0,
            "established_cvd": False,
            "known_ckd": False,
        },
        "expected_output": "Mounjaro",
    },
]
