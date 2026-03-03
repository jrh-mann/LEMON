"""Test fixtures: Workflow definitions and test cases"""

from typing import Dict, Any, List


# ============================================================================
# WORKFLOW 1: Simple Age Check (Basic Binary Decision)
# ============================================================================

SIMPLE_AGE_WORKFLOW = {
    "inputs": [
        {
            "id": "input_age_int",
            "name": "Age",
            "type": "number",
            "description": "Person's age in years",
            "range": {"min": 0, "max": 120}
        }
    ],
    "outputs": [
        {"name": "Adult", "description": "Person is 18 or older"},
        {"name": "Minor", "description": "Person is under 18"}
    ],
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
                    "input_ids": ["input_age_int"],
                    "condition": {
                        "input_id": "input_age_int",
                        "comparator": "gte",
                        "value": 18
                    },
                    "children": [
                        {
                            "id": "out_adult",
                            "type": "output",
                            "label": "Adult",
                            "edge_label": "Yes",
                            "children": []
                        },
                        {
                            "id": "out_minor",
                            "type": "output",
                            "label": "Minor",
                            "edge_label": "No",
                            "children": []
                        }
                    ]
                }
            ]
        }
    }
}

SIMPLE_AGE_TEST_CASES = [
    # (inputs, expected_output, description)
    ({"input_age_int": 18}, "Adult", "Exactly 18 (boundary)"),
    ({"input_age_int": 25}, "Adult", "Adult age"),
    ({"input_age_int": 17}, "Minor", "Just under 18"),
    ({"input_age_int": 0}, "Minor", "Newborn"),
    ({"input_age_int": 100}, "Adult", "Elderly"),
]


# ============================================================================
# WORKFLOW 2: Multi-Level Decision (Nested Conditions)
# ============================================================================

CHOLESTEROL_RISK_WORKFLOW = {
    "inputs": [
        {
            "id": "input_age_int",
            "name": "Age",
            "type": "number",
            "range": {"min": 0, "max": 120}
        },
        {
            "id": "input_cholesterol_float",
            "name": "Cholesterol",
            "type": "number",
            "range": {"min": 0, "max": 500}
        },
        {
            "id": "input_hdl_float",
            "name": "HDL",
            "type": "number",
            "range": {"min": 0, "max": 100}
        },
        {
            "id": "input_smoker_bool",
            "name": "Smoker",
            "type": "bool"
        }
    ],
    "outputs": [
        {"name": "High Risk", "description": "Recommend statin therapy"},
        {"name": "Moderate Risk", "description": "Monitor cholesterol"},
        {"name": "Low Risk", "description": "Routine screening"},
        {"name": "Too Young", "description": "Under 40, routine care"}
    ],
    "tree": {
        "start": {
            "id": "start",
            "type": "start",
            "label": "Start",
            "children": [
                {
                    "id": "age_check",
                    "type": "decision",
                    "label": "Age >= 40",
                    "input_ids": ["input_age_int"],
                    "condition": {
                        "input_id": "input_age_int",
                        "comparator": "gte",
                        "value": 40
                    },
                    "children": [
                        {
                            "id": "cholesterol_check",
                            "type": "decision",
                            "label": "Cholesterol >= 200",
                            "input_ids": ["input_cholesterol_float"],
                            "edge_label": "Yes",
                            "condition": {
                                "input_id": "input_cholesterol_float",
                                "comparator": "gte",
                                "value": 200
                            },
                            "children": [
                                {
                                    "id": "hdl_check",
                                    "type": "decision",
                                    "label": "HDL < 40",
                                    "input_ids": ["input_hdl_float"],
                                    "edge_label": "Yes",
                                    "condition": {
                                        "input_id": "input_hdl_float",
                                        "comparator": "lt",
                                        "value": 40
                                    },
                                    "children": [
                                        {
                                            "id": "smoker_check",
                                            "type": "decision",
                                            "label": "Smoker == True",
                                            "input_ids": ["input_smoker_bool"],
                                            "edge_label": "Yes",
                                            "condition": {
                                                "input_id": "input_smoker_bool",
                                                "comparator": "is_true",
                                                "value": None
                                            },
                                            "children": [
                                                {
                                                    "id": "out_high_risk",
                                                    "type": "output",
                                                    "label": "High Risk",
                                                    "edge_label": "Yes",
                                                    "children": []
                                                },
                                                {
                                                    "id": "out_moderate_risk",
                                                    "type": "output",
                                                    "label": "Moderate Risk",
                                                    "edge_label": "No",
                                                    "children": []
                                                }
                                            ]
                                        },
                                        {
                                            "id": "out_moderate_risk_hdl_no_smoke",
                                            "type": "output",
                                            "label": "Moderate Risk",
                                            "edge_label": "No",
                                            "children": []
                                        }
                                    ]
                                },
                                {
                                    "id": "out_low_risk",
                                    "type": "output",
                                    "label": "Low Risk",
                                    "edge_label": "No",
                                    "children": []
                                }
                            ]
                        },
                        {
                            "id": "out_too_young",
                            "type": "output",
                            "label": "Too Young",
                            "edge_label": "No",
                            "children": []
                        }
                    ]
                }
            ]
        }
    }
}

CHOLESTEROL_RISK_TEST_CASES = [
    # High Risk: Age >= 40, Cholesterol >= 200, HDL < 40, Smoker
    (
        {
            "input_age_int": 50,
            "input_cholesterol_float": 240.0,
            "input_hdl_float": 35.0,
            "input_smoker_bool": True
        },
        "High Risk",
        "High risk: all factors present"
    ),

    # Moderate Risk: Age >= 40, Cholesterol >= 200, but not (HDL < 40 AND Smoker)
    (
        {
            "input_age_int": 50,
            "input_cholesterol_float": 240.0,
            "input_hdl_float": 35.0,
            "input_smoker_bool": False  # Not smoker
        },
        "Moderate Risk",
        "Moderate risk: high cholesterol but not smoker"
    ),
    (
        {
            "input_age_int": 50,
            "input_cholesterol_float": 240.0,
            "input_hdl_float": 50.0,  # HDL >= 40
            "input_smoker_bool": True
        },
        "Moderate Risk",
        "Moderate risk: high cholesterol but good HDL"
    ),

    # Low Risk: Age >= 40, Cholesterol < 200
    (
        {
            "input_age_int": 50,
            "input_cholesterol_float": 180.0,
            "input_hdl_float": 35.0,
            "input_smoker_bool": True
        },
        "Low Risk",
        "Low risk: normal cholesterol despite other factors"
    ),

    # Too Young: Age < 40
    (
        {
            "input_age_int": 25,
            "input_cholesterol_float": 300.0,
            "input_hdl_float": 20.0,
            "input_smoker_bool": True
        },
        "Too Young",
        "Too young: age < 40 regardless of other factors"
    ),

    # Boundary cases
    (
        {
            "input_age_int": 40,  # Exactly 40
            "input_cholesterol_float": 200.0,  # Exactly 200
            "input_hdl_float": 40.0,  # Exactly 40
            "input_smoker_bool": True
        },
        "Moderate Risk",
        "Boundary: Age=40, Chol=200, HDL=40 (HDL NOT < 40)"
    ),
    (
        {
            "input_age_int": 39,  # Just under 40
            "input_cholesterol_float": 200.0,
            "input_hdl_float": 30.0,
            "input_smoker_bool": True
        },
        "Too Young",
        "Boundary: Age=39 (just under threshold)"
    ),
]


# ============================================================================
# WORKFLOW 3: OR Logic and String Comparison
# ============================================================================

MEDICATION_WORKFLOW = {
    "inputs": [
        {
            "id": "input_condition_enum",
            "name": "Condition",
            "type": "enum",
            "enum_values": ["Hypertension", "Diabetes", "Heart Disease", "None"]
        },
        {
            "id": "input_age_int",
            "name": "Age",
            "type": "number",
            "range": {"min": 0, "max": 120}
        },
        {
            "id": "input_pregnant_bool",
            "name": "Pregnant",
            "type": "bool"
        }
    ],
    "outputs": [
        {"name": "ACE Inhibitor"},
        {"name": "Beta Blocker"},
        {"name": "Lifestyle Changes Only"},
        {"name": "Contraindicated"}
    ],
    "tree": {
        "start": {
            "id": "start",
            "type": "start",
            "label": "Start",
            "children": [
                {
                    "id": "pregnancy_check",
                    "type": "decision",
                    "label": "Pregnant == True",
                    "input_ids": ["input_pregnant_bool"],
                    "condition": {
                        "input_id": "input_pregnant_bool",
                        "comparator": "is_true",
                        "value": None
                    },
                    "children": [
                        {
                            "id": "out_contraindicated",
                            "type": "output",
                            "label": "Contraindicated",
                            "edge_label": "Yes",
                            "children": []
                        },
                        {
                            "id": "hypertension_check",
                            "type": "decision",
                            "label": "Condition == Hypertension",
                            "input_ids": ["input_condition_enum"],
                            "edge_label": "No",
                            "condition": {
                                "input_id": "input_condition_enum",
                                "comparator": "enum_eq",
                                "value": "Hypertension"
                            },
                            "children": [
                                {
                                    "id": "age_check_hypertension",
                                    "type": "decision",
                                    "label": "Age >= 65",
                                    "input_ids": ["input_age_int"],
                                    "edge_label": "Yes",
                                    "condition": {
                                        "input_id": "input_age_int",
                                        "comparator": "gte",
                                        "value": 65
                                    },
                                    "children": [
                                        {
                                            "id": "out_beta_blocker",
                                            "type": "output",
                                            "label": "Beta Blocker",
                                            "edge_label": "Yes",
                                            "children": []
                                        },
                                        {
                                            "id": "out_ace_inhibitor",
                                            "type": "output",
                                            "label": "ACE Inhibitor",
                                            "edge_label": "No",
                                            "children": []
                                        }
                                    ]
                                },
                                {
                                    "id": "heart_disease_check",
                                    "type": "decision",
                                    "label": "Condition == Heart Disease",
                                    "input_ids": ["input_condition_enum"],
                                    "edge_label": "No",
                                    "condition": {
                                        "input_id": "input_condition_enum",
                                        "comparator": "enum_eq",
                                        "value": "Heart Disease"
                                    },
                                    "children": [
                                        {
                                            "id": "age_check_heart",
                                            "type": "decision",
                                            "label": "Age >= 65",
                                            "input_ids": ["input_age_int"],
                                            "edge_label": "Yes",
                                            "condition": {
                                                "input_id": "input_age_int",
                                                "comparator": "gte",
                                                "value": 65
                                            },
                                            "children": [
                                                {
                                                    "id": "out_beta_blocker_heart",
                                                    "type": "output",
                                                    "label": "Beta Blocker",
                                                    "edge_label": "Yes",
                                                    "children": []
                                                },
                                                {
                                                    "id": "out_ace_inhibitor_heart",
                                                    "type": "output",
                                                    "label": "ACE Inhibitor",
                                                    "edge_label": "No",
                                                    "children": []
                                                }
                                            ]
                                        },
                                        {
                                            "id": "out_lifestyle",
                                            "type": "output",
                                            "label": "Lifestyle Changes Only",
                                            "edge_label": "No",
                                            "children": []
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    }
}

MEDICATION_TEST_CASES = [
    # Contraindicated: Pregnant
    (
        {
            "input_condition_enum": "Hypertension",
            "input_age_int": 50,
            "input_pregnant_bool": True
        },
        "Contraindicated",
        "Pregnant: contraindicated regardless"
    ),

    # Beta Blocker: Not pregnant, (Hypertension OR Heart Disease), Age >= 65
    (
        {
            "input_condition_enum": "Hypertension",
            "input_age_int": 70,
            "input_pregnant_bool": False
        },
        "Beta Blocker",
        "Elderly with hypertension"
    ),
    (
        {
            "input_condition_enum": "Heart Disease",
            "input_age_int": 65,
            "input_pregnant_bool": False
        },
        "Beta Blocker",
        "Age 65 boundary with heart disease"
    ),

    # ACE Inhibitor: Not pregnant, (Hypertension OR Heart Disease), Age < 65
    (
        {
            "input_condition_enum": "Hypertension",
            "input_age_int": 50,
            "input_pregnant_bool": False
        },
        "ACE Inhibitor",
        "Middle-aged with hypertension"
    ),
    (
        {
            "input_condition_enum": "Heart Disease",
            "input_age_int": 64,
            "input_pregnant_bool": False
        },
        "ACE Inhibitor",
        "Age 64 with heart disease"
    ),

    # Lifestyle Changes: Not pregnant, NOT (Hypertension OR Heart Disease)
    (
        {
            "input_condition_enum": "Diabetes",
            "input_age_int": 50,
            "input_pregnant_bool": False
        },
        "Lifestyle Changes Only",
        "Diabetes (not hypertension or heart disease)"
    ),
    (
        {
            "input_condition_enum": "None",
            "input_age_int": 30,
            "input_pregnant_bool": False
        },
        "Lifestyle Changes Only",
        "No medical condition"
    ),
]


# ============================================================================
# WORKFLOW 4: Numeric Ranges and Complex Expressions
# ============================================================================

BMI_CLASSIFICATION_WORKFLOW = {
    "inputs": [
        {
            "id": "input_bmi_float",
            "name": "BMI",
            "type": "number",
            "range": {"min": 10, "max": 60}
        },
        {
            "id": "input_athlete_bool",
            "name": "Athlete",
            "type": "bool"
        }
    ],
    "outputs": [
        {"name": "Underweight"},
        {"name": "Normal"},
        {"name": "Athletic Build"},
        {"name": "Overweight"},
        {"name": "Obese"}
    ],
    "tree": {
        "start": {
            "id": "start",
            "type": "start",
            "label": "Start",
            "children": [
                {
                    "id": "bmi_check",
                    "type": "decision",
                    "label": "BMI < 18.5",
                    "input_ids": ["input_bmi_float"],
                    "condition": {
                        "input_id": "input_bmi_float",
                        "comparator": "lt",
                        "value": 18.5
                    },
                    "children": [
                        {
                            "id": "out_underweight",
                            "type": "output",
                            "label": "Underweight",
                            "edge_label": "Yes",
                            "children": []
                        },
                        {
                            "id": "normal_check",
                            "type": "decision",
                            "label": "BMI < 25",
                            "input_ids": ["input_bmi_float"],
                            "edge_label": "No",
                            "condition": {
                                "input_id": "input_bmi_float",
                                "comparator": "lt",
                                "value": 25
                            },
                            "children": [
                                {
                                    "id": "out_normal",
                                    "type": "output",
                                    "label": "Normal",
                                    "edge_label": "Yes",
                                    "children": []
                                },
                                {
                                    "id": "overweight_check",
                                    "type": "decision",
                                    "label": "BMI < 30",
                                    "input_ids": ["input_bmi_float"],
                                    "edge_label": "No",
                                    "condition": {
                                        "input_id": "input_bmi_float",
                                        "comparator": "lt",
                                        "value": 30
                                    },
                                    "children": [
                                        {
                                            "id": "athlete_check",
                                            "type": "decision",
                                            "label": "Athlete == True",
                                            "input_ids": ["input_athlete_bool"],
                                            "edge_label": "Yes",
                                            "condition": {
                                                "input_id": "input_athlete_bool",
                                                "comparator": "is_true",
                                                "value": None
                                            },
                                            "children": [
                                                {
                                                    "id": "out_athletic",
                                                    "type": "output",
                                                    "label": "Athletic Build",
                                                    "edge_label": "Yes",
                                                    "children": []
                                                },
                                                {
                                                    "id": "out_overweight",
                                                    "type": "output",
                                                    "label": "Overweight",
                                                    "edge_label": "No",
                                                    "children": []
                                                }
                                            ]
                                        },
                                        {
                                            "id": "out_obese",
                                            "type": "output",
                                            "label": "Obese",
                                            "edge_label": "No",
                                            "children": []
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    }
}

BMI_CLASSIFICATION_TEST_CASES = [
    # Underweight: BMI < 18.5
    (
        {"input_bmi_float": 17.0, "input_athlete_bool": False},
        "Underweight",
        "Underweight BMI"
    ),
    (
        {"input_bmi_float": 18.4, "input_athlete_bool": False},
        "Underweight",
        "Boundary: just under 18.5"
    ),

    # Normal: 18.5 <= BMI < 25
    (
        {"input_bmi_float": 18.5, "input_athlete_bool": False},
        "Normal",
        "Boundary: exactly 18.5"
    ),
    (
        {"input_bmi_float": 22.0, "input_athlete_bool": False},
        "Normal",
        "Normal BMI"
    ),
    (
        {"input_bmi_float": 24.9, "input_athlete_bool": False},
        "Normal",
        "Boundary: just under 25"
    ),

    # Athletic Build: 25 <= BMI < 30 AND Athlete
    (
        {"input_bmi_float": 27.0, "input_athlete_bool": True},
        "Athletic Build",
        "Athlete with higher BMI"
    ),
    (
        {"input_bmi_float": 25.0, "input_athlete_bool": True},
        "Athletic Build",
        "Boundary: BMI=25, athlete"
    ),

    # Overweight: 25 <= BMI < 30 AND NOT Athlete
    (
        {"input_bmi_float": 27.0, "input_athlete_bool": False},
        "Overweight",
        "Overweight, not athlete"
    ),
    (
        {"input_bmi_float": 29.9, "input_athlete_bool": False},
        "Overweight",
        "Boundary: just under 30"
    ),

    # Obese: BMI >= 30
    (
        {"input_bmi_float": 30.0, "input_athlete_bool": False},
        "Obese",
        "Boundary: exactly 30"
    ),
    (
        {"input_bmi_float": 35.0, "input_athlete_bool": True},
        "Obese",
        "Obese even if athlete"
    ),
]


# ============================================================================
# WORKFLOW 5: NOT operator and parentheses
# ============================================================================

ELIGIBILITY_WORKFLOW = {
    "inputs": [
        {
            "id": "input_age_int",
            "name": "Age",
            "type": "number",
            "range": {"min": 0, "max": 120}
        },
        {
            "id": "input_citizen_bool",
            "name": "Citizen",
            "type": "bool"
        },
        {
            "id": "input_convicted_bool",
            "name": "Convicted",
            "type": "bool"
        }
    ],
    "outputs": [
        {"name": "Eligible"},
        {"name": "Not Eligible - Age"},
        {"name": "Not Eligible - Citizenship"},
        {"name": "Not Eligible - Criminal Record"}
    ],
    "tree": {
        "start": {
            "id": "start",
            "type": "start",
            "label": "Start",
            "children": [
                {
                    "id": "age_check",
                    "type": "decision",
                    "label": "Age >= 18 AND Age <= 65",
                    "input_ids": ["input_age_int"],
                    "condition": {
                        "input_id": "input_age_int",
                        "comparator": "within_range",
                        "value": 18,
                        "value2": 65
                    },
                    "children": [
                        {
                            "id": "citizenship_check",
                            "type": "decision",
                            "label": "Citizen == True",
                            "input_ids": ["input_citizen_bool"],
                            "edge_label": "Yes",
                            "condition": {
                                "input_id": "input_citizen_bool",
                                "comparator": "is_true",
                                "value": None
                            },
                            "children": [
                                {
                                    "id": "criminal_check",
                                    "type": "decision",
                                    "label": "Convicted == False",
                                    "input_ids": ["input_convicted_bool"],
                                    "edge_label": "Yes",
                                    "condition": {
                                        "input_id": "input_convicted_bool",
                                        "comparator": "is_false",
                                        "value": None
                                    },
                                    "children": [
                                        {
                                            "id": "out_eligible",
                                            "type": "output",
                                            "label": "Eligible",
                                            "edge_label": "Yes",
                                            "children": []
                                        },
                                        {
                                            "id": "out_criminal",
                                            "type": "output",
                                            "label": "Not Eligible - Criminal Record",
                                            "edge_label": "No",
                                            "children": []
                                        }
                                    ]
                                },
                                {
                                    "id": "out_citizenship",
                                    "type": "output",
                                    "label": "Not Eligible - Citizenship",
                                    "edge_label": "No",
                                    "children": []
                                }
                            ]
                        },
                        {
                            "id": "out_age",
                            "type": "output",
                            "label": "Not Eligible - Age",
                            "edge_label": "No",
                            "children": []
                        }
                    ]
                }
            ]
        }
    }
}

ELIGIBILITY_TEST_CASES = [
    # Eligible: All conditions met
    (
        {
            "input_age_int": 30,
            "input_citizen_bool": True,
            "input_convicted_bool": False
        },
        "Eligible",
        "All conditions met"
    ),
    (
        {
            "input_age_int": 18,
            "input_citizen_bool": True,
            "input_convicted_bool": False
        },
        "Eligible",
        "Boundary: age 18"
    ),
    (
        {
            "input_age_int": 65,
            "input_citizen_bool": True,
            "input_convicted_bool": False
        },
        "Eligible",
        "Boundary: age 65"
    ),

    # Not Eligible - Age
    (
        {
            "input_age_int": 17,
            "input_citizen_bool": True,
            "input_convicted_bool": False
        },
        "Not Eligible - Age",
        "Too young"
    ),
    (
        {
            "input_age_int": 66,
            "input_citizen_bool": True,
            "input_convicted_bool": False
        },
        "Not Eligible - Age",
        "Too old"
    ),

    # Not Eligible - Citizenship
    (
        {
            "input_age_int": 30,
            "input_citizen_bool": False,
            "input_convicted_bool": False
        },
        "Not Eligible - Citizenship",
        "Not a citizen"
    ),

    # Not Eligible - Criminal Record
    (
        {
            "input_age_int": 30,
            "input_citizen_bool": True,
            "input_convicted_bool": True
        },
        "Not Eligible - Criminal Record",
        "Convicted felon"
    ),
]


# ============================================================================
# ERROR TEST CASES
# ============================================================================

ERROR_TEST_CASES = [
    # Missing required inputs
    (
        SIMPLE_AGE_WORKFLOW,
        {},
        None,
        "Missing required input: input_age_int"
    ),

    # Type mismatch
    (
        SIMPLE_AGE_WORKFLOW,
        {"input_age_int": "not a number"},
        None,
        "Type error: input_age_int must be int"
    ),

    # Out of range
    (
        SIMPLE_AGE_WORKFLOW,
        {"input_age_int": 150},
        None,
        "Value error: input_age_int=150 exceeds maximum 120"
    ),

    # Invalid enum value
    (
        MEDICATION_WORKFLOW,
        {
            "input_condition_enum": "Cancer",  # Not in enum
            "input_age_int": 50,
            "input_pregnant_bool": False
        },
        None,
        "Value error: input_condition_enum must be one of"
    ),
]


# ============================================================================
# Helper to get all test suites
# ============================================================================

def get_all_workflow_tests():
    """Returns list of (workflow, test_cases, name) tuples"""
    return [
        (SIMPLE_AGE_WORKFLOW, SIMPLE_AGE_TEST_CASES, "Simple Age Check"),
        (CHOLESTEROL_RISK_WORKFLOW, CHOLESTEROL_RISK_TEST_CASES, "Cholesterol Risk Assessment"),
        (MEDICATION_WORKFLOW, MEDICATION_TEST_CASES, "Medication Decision"),
        (BMI_CLASSIFICATION_WORKFLOW, BMI_CLASSIFICATION_TEST_CASES, "BMI Classification"),
        (ELIGIBILITY_WORKFLOW, ELIGIBILITY_TEST_CASES, "Eligibility Check"),
    ]
