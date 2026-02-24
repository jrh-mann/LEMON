"""Ground-truth treatment logic for ``Diabetes Treatment .png``."""

from __future__ import annotations

from typing import Any, Dict, List


INPUT_SCHEMA = [
    {"name": "symptoms_and_new_a1c_gt_58", "type": "bool"},
    {"name": "admission_required", "type": "bool"},
    {"name": "cvd_known_or_risk", "type": "bool"},
    {"name": "metformin_tolerated", "type": "bool"},
    {"name": "a1c_after_metformin", "type": "float"},
    {"name": "a1c_after_sglt2i", "type": "float"},
    {"name": "a1c_after_dual_therapy", "type": "float"},
    {"name": "a1c_after_triple_therapy", "type": "float"},
    {"name": "a1c_after_glp", "type": "float"},
    {"name": "dual_agent_choice", "type": "string"},
    {"name": "bmi", "type": "float"},
    {"name": "high_prognostic_value", "type": "bool"},
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

TEST_CASES: List[Dict[str, Any]] = [
    {
        "inputs": {
            "symptoms_and_new_a1c_gt_58": True,
            "admission_required": True,
            "cvd_known_or_risk": True,
            "metformin_tolerated": True,
            "a1c_after_metformin": 62.0,
            "a1c_after_sglt2i": 60.0,
            "a1c_after_dual_therapy": 61.0,
            "a1c_after_triple_therapy": 60.0,
            "a1c_after_glp": 59.0,
            "dual_agent_choice": "gliptin",
            "bmi": 30.0,
            "high_prognostic_value": True,
        },
        "expected_output": "Admit via A&E/Medics",
    },
    {
        "inputs": {
            "symptoms_and_new_a1c_gt_58": True,
            "admission_required": False,
            "cvd_known_or_risk": False,
            "metformin_tolerated": True,
            "a1c_after_metformin": 62.0,
            "a1c_after_sglt2i": 60.0,
            "a1c_after_dual_therapy": 61.0,
            "a1c_after_triple_therapy": 60.0,
            "a1c_after_glp": 59.0,
            "dual_agent_choice": "gliptin",
            "bmi": 30.0,
            "high_prognostic_value": True,
        },
        "expected_output": "Start Gliclazide or Insulin",
    },
    {
        "inputs": {
            "symptoms_and_new_a1c_gt_58": False,
            "admission_required": False,
            "cvd_known_or_risk": True,
            "metformin_tolerated": True,
            "a1c_after_metformin": 47.0,
            "a1c_after_sglt2i": 52.0,
            "a1c_after_dual_therapy": 54.0,
            "a1c_after_triple_therapy": 57.0,
            "a1c_after_glp": 56.0,
            "dual_agent_choice": "gliptin",
            "bmi": 29.0,
            "high_prognostic_value": True,
        },
        "expected_output": "Metformin (continue and review in 3 months)",
    },
    {
        "inputs": {
            "symptoms_and_new_a1c_gt_58": False,
            "admission_required": False,
            "cvd_known_or_risk": True,
            "metformin_tolerated": True,
            "a1c_after_metformin": 55.0,
            "a1c_after_sglt2i": 52.0,
            "a1c_after_dual_therapy": 58.0,
            "a1c_after_triple_therapy": 59.0,
            "a1c_after_glp": 59.0,
            "dual_agent_choice": "gliptin",
            "bmi": 29.0,
            "high_prognostic_value": True,
        },
        "expected_output": "SGLT2i (continue and review in 3 months)",
    },
    {
        "inputs": {
            "symptoms_and_new_a1c_gt_58": False,
            "admission_required": False,
            "cvd_known_or_risk": True,
            "metformin_tolerated": False,
            "a1c_after_metformin": 58.0,
            "a1c_after_sglt2i": 54.0,
            "a1c_after_dual_therapy": 59.0,
            "a1c_after_triple_therapy": 59.0,
            "a1c_after_glp": 57.0,
            "dual_agent_choice": "gliptin",
            "bmi": 31.0,
            "high_prognostic_value": True,
        },
        "expected_output": "Ozempic titrate to full dose with 3 monthly A1c's",
    },
    {
        "inputs": {
            "symptoms_and_new_a1c_gt_58": False,
            "admission_required": False,
            "cvd_known_or_risk": True,
            "metformin_tolerated": True,
            "a1c_after_metformin": 60.0,
            "a1c_after_sglt2i": 58.0,
            "a1c_after_dual_therapy": 58.0,
            "a1c_after_triple_therapy": 59.0,
            "a1c_after_glp": 60.0,
            "dual_agent_choice": "gliptin",
            "bmi": 31.0,
            "high_prognostic_value": True,
        },
        "expected_output": "Refer to Insulin Initiator",
    },
    {
        "inputs": {
            "symptoms_and_new_a1c_gt_58": False,
            "admission_required": False,
            "cvd_known_or_risk": False,
            "metformin_tolerated": True,
            "a1c_after_metformin": 47.0,
            "a1c_after_sglt2i": 56.0,
            "a1c_after_dual_therapy": 56.0,
            "a1c_after_triple_therapy": 58.0,
            "a1c_after_glp": 57.0,
            "dual_agent_choice": "gliptin",
            "bmi": 28.0,
            "high_prognostic_value": False,
        },
        "expected_output": "Metformin (continue and review in 3 months)",
    },
    {
        "inputs": {
            "symptoms_and_new_a1c_gt_58": False,
            "admission_required": False,
            "cvd_known_or_risk": False,
            "metformin_tolerated": True,
            "a1c_after_metformin": 54.0,
            "a1c_after_sglt2i": 57.0,
            "a1c_after_dual_therapy": 52.0,
            "a1c_after_triple_therapy": 58.0,
            "a1c_after_glp": 58.0,
            "dual_agent_choice": "gliclazide",
            "bmi": 27.0,
            "high_prognostic_value": False,
        },
        "expected_output": "Metformin + Gliclazide",
    },
    {
        "inputs": {
            "symptoms_and_new_a1c_gt_58": False,
            "admission_required": False,
            "cvd_known_or_risk": False,
            "metformin_tolerated": True,
            "a1c_after_metformin": 54.0,
            "a1c_after_sglt2i": 57.0,
            "a1c_after_dual_therapy": 55.0,
            "a1c_after_triple_therapy": 57.0,
            "a1c_after_glp": 59.0,
            "dual_agent_choice": "pioglitazone",
            "bmi": 27.0,
            "high_prognostic_value": False,
        },
        "expected_output": "Metformin + Gliptin/Pioglitazone/Gliclazide (consider SGLT2i)",
    },
    {
        "inputs": {
            "symptoms_and_new_a1c_gt_58": False,
            "admission_required": False,
            "cvd_known_or_risk": False,
            "metformin_tolerated": True,
            "a1c_after_metformin": 55.0,
            "a1c_after_sglt2i": 57.0,
            "a1c_after_dual_therapy": 56.0,
            "a1c_after_triple_therapy": 59.0,
            "a1c_after_glp": 57.0,
            "dual_agent_choice": "gliptin",
            "bmi": 30.0,
            "high_prognostic_value": True,
        },
        "expected_output": "Ozempic",
    },
    {
        "inputs": {
            "symptoms_and_new_a1c_gt_58": False,
            "admission_required": False,
            "cvd_known_or_risk": False,
            "metformin_tolerated": True,
            "a1c_after_metformin": 55.0,
            "a1c_after_sglt2i": 57.0,
            "a1c_after_dual_therapy": 56.0,
            "a1c_after_triple_therapy": 59.0,
            "a1c_after_glp": 57.0,
            "dual_agent_choice": "gliptin",
            "bmi": 30.0,
            "high_prognostic_value": False,
        },
        "expected_output": "Mounjaro",
    },
    {
        "inputs": {
            "symptoms_and_new_a1c_gt_58": False,
            "admission_required": False,
            "cvd_known_or_risk": False,
            "metformin_tolerated": True,
            "a1c_after_metformin": 55.0,
            "a1c_after_sglt2i": 57.0,
            "a1c_after_dual_therapy": 56.0,
            "a1c_after_triple_therapy": 60.0,
            "a1c_after_glp": 60.0,
            "dual_agent_choice": "gliptin",
            "bmi": 22.0,
            "high_prognostic_value": False,
        },
        "expected_output": "Metformin + Gliptin/Pioglitazone/Gliclazide (consider SGLT2i)",
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


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _a1c_controlled(stage_a1c: float | None, threshold: float) -> bool:
    return stage_a1c is not None and stage_a1c <= threshold


def _normalise_dual_agent(raw: Any) -> str:
    choice = str(raw or "").strip().lower()
    if choice in {"gliptin", "pioglitazone", "gliclazide"}:
        return choice
    return "gliptin"


def determine_workflow_outcome(inputs: Dict[str, Any]) -> str:
    """Return the next recommended action for the diabetes treatment algorithm."""
    symptoms_and_new_a1c_gt_58 = _as_bool(inputs.get("symptoms_and_new_a1c_gt_58"))
    admission_required = _as_bool(inputs.get("admission_required"))

    if symptoms_and_new_a1c_gt_58:
        if admission_required:
            return "Admit via A&E/Medics"
        return "Start Gliclazide or Insulin"

    cvd_known_or_risk = _as_bool(inputs.get("cvd_known_or_risk"))
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
        if _as_bool(inputs.get("high_prognostic_value")):
            return "Ozempic"
        return "Mounjaro"

    return "Refer to Insulin Initiator"
