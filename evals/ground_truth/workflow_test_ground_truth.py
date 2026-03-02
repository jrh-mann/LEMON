"""Ground truth for ``workflow_test.jpeg`` (lipid management workflow).

This module keeps compatibility with historical eval inputs while expanding
subworkflow derivations for:
- primary vs secondary prevention classification
- treatment optimization checks
- secondary prevention escalation ordering
"""

from __future__ import annotations

from typing import Any, Dict, List


INPUT_SCHEMA = [
    {"name": "under_specialist_clinic", "type": "bool"},
    {"name": "total_cholesterol", "type": "float"},
    {"name": "prevention_type", "type": "string"},
    {"name": "taking_lipid_lowering_therapy", "type": "bool"},
    {"name": "optimised_on_treatment", "type": "bool"},
    {"name": "qrisk2_3_score", "type": "float"},
    {"name": "taking_maximally_tolerated_statin", "type": "bool"},
    {"name": "ldl_cholesterol", "type": "float"},
    {"name": "months_on_inclisiran", "type": "int"},
    # Expanded derivation support.
    {"name": "known_chd", "type": "bool"},
    {"name": "known_pad", "type": "bool"},
    {"name": "known_ischemic_stroke", "type": "bool"},
    {"name": "known_cad", "type": "bool"},
    {"name": "known_prior_mi", "type": "bool"},
    {"name": "on_high_intensity_statin", "type": "bool"},
    {"name": "statin_intolerant", "type": "bool"},
    {"name": "ezetimibe_started", "type": "bool"},
]

POSSIBLE_OUTPUTS = [
    "No Further Action",
    "Mark as Satisfactory",
    'Mark as "No Further Action"',
    'Send "Lipid Lowering Therapy" AccuRx with self booking link',
    'Send "High Cholesterol - Low QRISK" AccuRx with self booking link',
    "Consider Lipid Clinic Referral",
    "Add in Ezetimibe",
    "Initiate Inclisiran",
    "Repeat Lipids at 3 months",
]


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on", "secondary"}
    return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def classify_prevention_type(inputs: Dict[str, Any]) -> str:
    explicit = str(inputs.get("prevention_type", "")).strip().lower()
    if explicit.startswith("primary"):
        return "Primary"
    if explicit.startswith("secondary"):
        return "Secondary"

    has_secondary_history = any(
        _as_bool(inputs.get(key))
        for key in (
            "known_chd",
            "known_pad",
            "known_ischemic_stroke",
            "known_cad",
            "known_prior_mi",
        )
    )
    return "Secondary" if has_secondary_history else "Primary"


def derive_optimised_on_treatment(inputs: Dict[str, Any]) -> bool:
    if "optimised_on_treatment" in inputs:
        return _as_bool(inputs.get("optimised_on_treatment"))

    on_high_intensity = _as_bool(inputs.get("on_high_intensity_statin"))
    statin_intolerant = _as_bool(inputs.get("statin_intolerant"))
    ezetimibe_started = _as_bool(inputs.get("ezetimibe_started"))
    max_tolerated = _as_bool(inputs.get("taking_maximally_tolerated_statin"))

    if max_tolerated:
        return True
    if statin_intolerant and ezetimibe_started:
        return True
    return on_high_intensity


def derive_maximally_tolerated_statin(inputs: Dict[str, Any]) -> bool:
    if "taking_maximally_tolerated_statin" in inputs:
        return _as_bool(inputs.get("taking_maximally_tolerated_statin"))
    return derive_optimised_on_treatment(inputs)


def determine_secondary_escalation(ldl_cholesterol: float) -> str:
    if ldl_cholesterol <= 2.0:
        return "No Further Action"
    if ldl_cholesterol <= 2.5:
        return "Add in Ezetimibe"
    return "Initiate Inclisiran"


def determine_workflow_outcome(inputs: Dict[str, Any]) -> str:
    """Deterministic outcome function based on the lipid workflow."""
    under_specialist_clinic = _as_bool(inputs.get("under_specialist_clinic"))
    total_cholesterol = _as_float(inputs.get("total_cholesterol"))
    prevention_type = classify_prevention_type(inputs)
    taking_lipid_lowering_therapy = _as_bool(inputs.get("taking_lipid_lowering_therapy"))
    optimised_on_treatment = derive_optimised_on_treatment(inputs)
    qrisk2_3_score = _as_float(inputs.get("qrisk2_3_score"))
    taking_maximally_tolerated_statin = derive_maximally_tolerated_statin(inputs)
    ldl_cholesterol = _as_float(inputs.get("ldl_cholesterol"))
    months_on_inclisiran = _as_int(inputs.get("months_on_inclisiran"))

    if months_on_inclisiran >= 6 and ldl_cholesterol > 2.6:
        return "Repeat Lipids at 3 months"

    if total_cholesterol > 7.5:
        if under_specialist_clinic:
            return "No Further Action"
        if optimised_on_treatment:
            return "Consider Lipid Clinic Referral"
        return 'Send "Lipid Lowering Therapy" AccuRx with self booking link'

    if total_cholesterol > 5.0:
        if taking_lipid_lowering_therapy:
            if optimised_on_treatment:
                return 'Mark as "No Further Action"'
            return 'Send "Lipid Lowering Therapy" AccuRx with self booking link'

        if prevention_type == "Primary":
            if qrisk2_3_score >= 10:
                return 'Send "Lipid Lowering Therapy" AccuRx with self booking link'
            return 'Send "High Cholesterol - Low QRISK" AccuRx with self booking link'

        if not taking_maximally_tolerated_statin:
            return 'Send "Lipid Lowering Therapy" AccuRx with self booking link'

        return determine_secondary_escalation(ldl_cholesterol)

    return "Mark as Satisfactory"


TEST_CASES: List[Dict[str, Any]] = [
    {
        "inputs": {
            "under_specialist_clinic": True,
            "total_cholesterol": 8.2,
            "taking_lipid_lowering_therapy": False,
            "optimised_on_treatment": False,
            "qrisk2_3_score": 3.0,
            "taking_maximally_tolerated_statin": False,
            "ldl_cholesterol": 3.0,
            "months_on_inclisiran": 0,
        },
        "expected_output": "No Further Action",
    },
    {
        "inputs": {
            "under_specialist_clinic": False,
            "total_cholesterol": 8.2,
            "taking_lipid_lowering_therapy": False,
            "optimised_on_treatment": True,
            "qrisk2_3_score": 3.0,
            "taking_maximally_tolerated_statin": False,
            "ldl_cholesterol": 3.0,
            "months_on_inclisiran": 0,
        },
        "expected_output": "Consider Lipid Clinic Referral",
    },
    {
        "inputs": {
            "under_specialist_clinic": False,
            "total_cholesterol": 6.3,
            "prevention_type": "Primary",
            "taking_lipid_lowering_therapy": False,
            "optimised_on_treatment": False,
            "qrisk2_3_score": 9.9,
            "taking_maximally_tolerated_statin": False,
            "ldl_cholesterol": 2.8,
            "months_on_inclisiran": 0,
        },
        "expected_output": 'Send "High Cholesterol - Low QRISK" AccuRx with self booking link',
    },
    {
        "inputs": {
            "under_specialist_clinic": False,
            "total_cholesterol": 6.3,
            "known_chd": True,
            "taking_lipid_lowering_therapy": False,
            "optimised_on_treatment": False,
            "qrisk2_3_score": 20.0,
            "taking_maximally_tolerated_statin": True,
            "ldl_cholesterol": 2.3,
            "months_on_inclisiran": 0,
        },
        "expected_output": "Add in Ezetimibe",
    },
    {
        "inputs": {
            "under_specialist_clinic": False,
            "total_cholesterol": 6.3,
            "known_cad": True,
            "taking_lipid_lowering_therapy": False,
            "optimised_on_treatment": False,
            "qrisk2_3_score": 20.0,
            "taking_maximally_tolerated_statin": True,
            "ldl_cholesterol": 3.1,
            "months_on_inclisiran": 0,
        },
        "expected_output": "Initiate Inclisiran",
    },
    {
        "inputs": {
            "under_specialist_clinic": False,
            "total_cholesterol": 6.3,
            "known_prior_mi": True,
            "taking_lipid_lowering_therapy": False,
            "optimised_on_treatment": False,
            "qrisk2_3_score": 20.0,
            "taking_maximally_tolerated_statin": True,
            "ldl_cholesterol": 2.7,
            "months_on_inclisiran": 7,
        },
        "expected_output": "Repeat Lipids at 3 months",
    },
]
