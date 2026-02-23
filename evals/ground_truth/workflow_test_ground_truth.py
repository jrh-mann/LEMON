"""Ground truth for ``workflow_test.jpeg``.

Seeded from ``origin/GroundTruth:workflow_code.py`` and normalized into a
stable schema for eval scoring.
"""

from __future__ import annotations

from typing import Any, Dict, List


INPUT_SCHEMA = [
    {"name": "under_specialist_clinic", "type": "bool"},
    {"name": "total_cholesterol", "type": "float"},
    {"name": "prevention_type", "type": "string"},  # Primary | Secondary
    {"name": "taking_lipid_lowering_therapy", "type": "bool"},
    {"name": "optimised_on_treatment", "type": "bool"},
    {"name": "qrisk2_3_score", "type": "float"},
    {"name": "taking_maximally_tolerated_statin", "type": "bool"},
    {"name": "ldl_cholesterol", "type": "float"},
    {"name": "months_on_inclisiran", "type": "int"},
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


TEST_CASES: List[Dict[str, Any]] = [
    {
        "inputs": {
            "under_specialist_clinic": True,
            "total_cholesterol": 8.2,
            "prevention_type": "Primary",
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
            "prevention_type": "Primary",
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
            "total_cholesterol": 8.2,
            "prevention_type": "Primary",
            "taking_lipid_lowering_therapy": False,
            "optimised_on_treatment": False,
            "qrisk2_3_score": 3.0,
            "taking_maximally_tolerated_statin": False,
            "ldl_cholesterol": 3.0,
            "months_on_inclisiran": 0,
        },
        "expected_output": 'Send "Lipid Lowering Therapy" AccuRx with self booking link',
    },
    {
        "inputs": {
            "under_specialist_clinic": False,
            "total_cholesterol": 4.9,
            "prevention_type": "Primary",
            "taking_lipid_lowering_therapy": False,
            "optimised_on_treatment": False,
            "qrisk2_3_score": 6.0,
            "taking_maximally_tolerated_statin": False,
            "ldl_cholesterol": 1.8,
            "months_on_inclisiran": 0,
        },
        "expected_output": "Mark as Satisfactory",
    },
    {
        "inputs": {
            "under_specialist_clinic": False,
            "total_cholesterol": 6.3,
            "prevention_type": "Primary",
            "taking_lipid_lowering_therapy": True,
            "optimised_on_treatment": True,
            "qrisk2_3_score": 12.0,
            "taking_maximally_tolerated_statin": False,
            "ldl_cholesterol": 2.8,
            "months_on_inclisiran": 0,
        },
        "expected_output": 'Mark as "No Further Action"',
    },
    {
        "inputs": {
            "under_specialist_clinic": False,
            "total_cholesterol": 6.3,
            "prevention_type": "Primary",
            "taking_lipid_lowering_therapy": True,
            "optimised_on_treatment": False,
            "qrisk2_3_score": 12.0,
            "taking_maximally_tolerated_statin": False,
            "ldl_cholesterol": 2.8,
            "months_on_inclisiran": 0,
        },
        "expected_output": 'Send "Lipid Lowering Therapy" AccuRx with self booking link',
    },
    {
        "inputs": {
            "under_specialist_clinic": False,
            "total_cholesterol": 6.3,
            "prevention_type": "Primary",
            "taking_lipid_lowering_therapy": False,
            "optimised_on_treatment": False,
            "qrisk2_3_score": 15.0,
            "taking_maximally_tolerated_statin": False,
            "ldl_cholesterol": 2.8,
            "months_on_inclisiran": 0,
        },
        "expected_output": 'Send "Lipid Lowering Therapy" AccuRx with self booking link',
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
            "prevention_type": "Secondary",
            "taking_lipid_lowering_therapy": False,
            "optimised_on_treatment": False,
            "qrisk2_3_score": 20.0,
            "taking_maximally_tolerated_statin": False,
            "ldl_cholesterol": 2.8,
            "months_on_inclisiran": 0,
        },
        "expected_output": 'Send "Lipid Lowering Therapy" AccuRx with self booking link',
    },
    {
        "inputs": {
            "under_specialist_clinic": False,
            "total_cholesterol": 6.3,
            "prevention_type": "Secondary",
            "taking_lipid_lowering_therapy": False,
            "optimised_on_treatment": False,
            "qrisk2_3_score": 20.0,
            "taking_maximally_tolerated_statin": True,
            "ldl_cholesterol": 1.9,
            "months_on_inclisiran": 0,
        },
        "expected_output": "No Further Action",
    },
    {
        "inputs": {
            "under_specialist_clinic": False,
            "total_cholesterol": 6.3,
            "prevention_type": "Secondary",
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
            "prevention_type": "Secondary",
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
            "prevention_type": "Secondary",
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


def determine_workflow_outcome(inputs: Dict[str, Any]) -> str:
    """Deterministic outcome function based on the workflow_test chart."""
    under_specialist_clinic = _as_bool(inputs.get("under_specialist_clinic"))
    total_cholesterol = _as_float(inputs.get("total_cholesterol"))
    prevention_type = str(inputs.get("prevention_type", "Primary"))
    taking_lipid_lowering_therapy = _as_bool(inputs.get("taking_lipid_lowering_therapy"))
    optimised_on_treatment = _as_bool(inputs.get("optimised_on_treatment"))
    qrisk2_3_score = _as_float(inputs.get("qrisk2_3_score"))
    taking_maximally_tolerated_statin = _as_bool(inputs.get("taking_maximally_tolerated_statin"))
    ldl_cholesterol = _as_float(inputs.get("ldl_cholesterol"))
    months_on_inclisiran = _as_int(inputs.get("months_on_inclisiran"))

    # Repeat-check guard after inclisiran path.
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

        if prevention_type.lower().startswith("primary"):
            if qrisk2_3_score >= 10:
                return 'Send "Lipid Lowering Therapy" AccuRx with self booking link'
            return 'Send "High Cholesterol - Low QRISK" AccuRx with self booking link'

        # Secondary prevention branch
        if not taking_maximally_tolerated_statin:
            return 'Send "Lipid Lowering Therapy" AccuRx with self booking link'

        if ldl_cholesterol <= 2.0:
            return "No Further Action"
        if ldl_cholesterol <= 2.5:
            return "Add in Ezetimibe"
        return "Initiate Inclisiran"

    return "Mark as Satisfactory"
