"""Ground-truth treatment logic for `Diabetes Treatment .png`.

This file is intentionally deterministic and mirrors the current workflow style:
- explicit inputs
- explicit decision branches
- single textual recommendation output
"""

from __future__ import annotations

from typing import Any, Dict


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
    {"name": "dual_agent_choice", "type": "string"},  # gliptin|pioglitazone|gliclazide
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

    # Entry triage path from the top-left branch.
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

    # Targets from the image notes:
    # 1 med <= 48, 2 meds <= 53, 3 meds <= 58.
    controlled_metformin = _a1c_controlled(a1c_after_metformin, 48.0)
    controlled_sglt2i = _a1c_controlled(a1c_after_sglt2i, 53.0)
    controlled_dual = _a1c_controlled(a1c_after_dual, 53.0)
    controlled_triple = _a1c_controlled(a1c_after_triple, 58.0)
    controlled_glp = _a1c_controlled(a1c_after_glp, 58.0)

    if cvd_known_or_risk:
        if controlled_metformin:
            return "Metformin (continue and review in 3 months)"

        # High-risk branch: Metformin -> SGLT2i -> Ozempic titration -> insulin referral.
        if metformin_tolerated and controlled_sglt2i:
            return "SGLT2i (continue and review in 3 months)"
        if not metformin_tolerated and controlled_sglt2i:
            return "SGLT2i (continue and review in 3 months)"

        if controlled_glp:
            return "Ozempic titrate to full dose with 3 monthly A1c's"
        return "Refer to Insulin Initiator"

    # Not-at-risk branch: step-up from metformin to dual/triple/GLP.
    if controlled_metformin:
        return "Metformin (continue and review in 3 months)"

    dual_choice = _normalise_dual_agent(inputs.get("dual_agent_choice"))
    if controlled_dual:
        return f"Metformin + {dual_choice.title()}"

    if controlled_triple:
        return "Metformin + Gliptin/Pioglitazone/Gliclazide (consider SGLT2i)"

    bmi = _as_float(inputs.get("bmi")) or 0.0
    if bmi < 23.0:
        # Image note: minimum BMI for GLP initiation is 23.
        return "Metformin + Gliptin/Pioglitazone/Gliclazide (consider SGLT2i)"

    if controlled_glp:
        if _as_bool(inputs.get("high_prognostic_value")):
            return "Ozempic"
        return "Mounjaro"

    return "Refer to Insulin Initiator"

