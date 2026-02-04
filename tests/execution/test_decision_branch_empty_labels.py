"""Tests for decision node branch selection with empty/missing edge labels.

This tests the bug where decision nodes fall back to the first child when
edge labels are empty, causing incorrect branch selection (e.g., BMI < 16
evaluating to True when BMI = 23.45).

Root cause: When edge labels are empty or missing, _find_branch() falls back
to children[0] regardless of the condition result.
"""

import pytest
from src.backend.execution.interpreter import TreeInterpreter


class TestEmptyEdgeLabelBranchSelection:
    """Test branch selection when edge labels are empty or missing."""

    def test_empty_edge_labels_false_condition_takes_wrong_branch(self):
        """BUG: When edge labels are empty, False condition takes True branch.
        
        This reproduces the user's BMI bug:
        - BMI = 23.45, condition BMI < 16 should be False
        - Should take False branch (Normal weight)
        - Actually takes True branch (Underweight) because of fallback to first child
        """
        # Workflow with EMPTY edge labels (simulating the bug scenario)
        workflow = {
            "inputs": [
                {
                    "id": "bmi",
                    "name": "BMI",
                    "type": "number",
                    "range": {"min": 0, "max": 100}
                }
            ],
            "outputs": [
                {"name": "Underweight", "description": "BMI < 16"},
                {"name": "Normal", "description": "BMI >= 16"}
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
                            "label": "BMI < 16",
                            "input_ids": ["bmi"],
                            "condition": {
                                "input_id": "bmi",
                                "comparator": "lt",
                                "value": 16
                            },
                            "children": [
                                {
                                    "id": "out_underweight",
                                    "type": "output",
                                    "label": "Underweight",
                                    "edge_label": "",  # EMPTY - bug trigger
                                    "children": []
                                },
                                {
                                    "id": "out_normal",
                                    "type": "output",
                                    "label": "Normal",
                                    "edge_label": "",  # EMPTY - bug trigger
                                    "children": []
                                }
                            ]
                        }
                    ]
                }
            }
        }

        interpreter = TreeInterpreter(
            tree=workflow["tree"],
            inputs=workflow["inputs"],
            outputs=workflow["outputs"]
        )

        # BMI = 23.45, condition "BMI < 16" is FALSE
        # Should take False branch -> "Normal"
        result = interpreter.execute({"bmi": 23.45})
        
        assert result.success is True, f"Execution failed: {result.error}"
        # This assertion currently FAILS due to the bug
        assert result.output == "Normal", (
            f"Expected 'Normal' for BMI=23.45 (condition BMI<16 is False), "
            f"but got '{result.output}'. Branch selection fallback bug!"
        )

    def test_missing_edge_labels_false_condition_takes_wrong_branch(self):
        """BUG: When edge_label key is missing, False condition takes True branch."""
        # Workflow with NO edge_label keys at all
        workflow = {
            "inputs": [
                {
                    "id": "age",
                    "name": "Age",
                    "type": "number",
                    "range": {"min": 0, "max": 120}
                }
            ],
            "outputs": [
                {"name": "Senior", "description": "Age > 65"},
                {"name": "Not Senior", "description": "Age <= 65"}
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
                            "label": "Age > 65",
                            "input_ids": ["age"],
                            "condition": {
                                "input_id": "age",
                                "comparator": "gt",
                                "value": 65
                            },
                            "children": [
                                {
                                    "id": "out_senior",
                                    "type": "output",
                                    "label": "Senior",
                                    # NO edge_label key - bug trigger
                                    "children": []
                                },
                                {
                                    "id": "out_not_senior",
                                    "type": "output",
                                    "label": "Not Senior",
                                    # NO edge_label key - bug trigger
                                    "children": []
                                }
                            ]
                        }
                    ]
                }
            }
        }

        interpreter = TreeInterpreter(
            tree=workflow["tree"],
            inputs=workflow["inputs"],
            outputs=workflow["outputs"]
        )

        # Age = 30, condition "Age > 65" is FALSE
        # Should take False branch -> "Not Senior"
        result = interpreter.execute({"age": 30})
        
        assert result.success is True, f"Execution failed: {result.error}"
        # This assertion currently FAILS due to the bug
        assert result.output == "Not Senior", (
            f"Expected 'Not Senior' for Age=30 (condition Age>65 is False), "
            f"but got '{result.output}'. Branch selection fallback bug!"
        )

    def test_empty_edge_labels_true_condition_works_by_accident(self):
        """When condition is True and first child is True branch, it works by accident."""
        workflow = {
            "inputs": [
                {
                    "id": "bmi",
                    "name": "BMI",
                    "type": "number",
                    "range": {"min": 0, "max": 100}
                }
            ],
            "outputs": [
                {"name": "Underweight", "description": "BMI < 16"},
                {"name": "Normal", "description": "BMI >= 16"}
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
                            "label": "BMI < 16",
                            "input_ids": ["bmi"],
                            "condition": {
                                "input_id": "bmi",
                                "comparator": "lt",
                                "value": 16
                            },
                            "children": [
                                {
                                    "id": "out_underweight",
                                    "type": "output",
                                    "label": "Underweight",
                                    "edge_label": "",  # EMPTY
                                    "children": []
                                },
                                {
                                    "id": "out_normal",
                                    "type": "output",
                                    "label": "Normal",
                                    "edge_label": "",  # EMPTY
                                    "children": []
                                }
                            ]
                        }
                    ]
                }
            }
        }

        interpreter = TreeInterpreter(
            tree=workflow["tree"],
            inputs=workflow["inputs"],
            outputs=workflow["outputs"]
        )

        # BMI = 14, condition "BMI < 16" is TRUE
        # First child happens to be "Underweight" (True branch)
        # So fallback to first child gives correct answer BY ACCIDENT
        result = interpreter.execute({"bmi": 14})
        
        assert result.success is True, f"Execution failed: {result.error}"
        # This works by accident because True branch is first
        assert result.output == "Underweight"


class TestPositionBasedFallback:
    """Test that position-based fallback works correctly when labels are missing.
    
    Convention: When edge labels are missing/empty, use position:
    - First child (index 0) = True branch
    - Second child (index 1) = False branch
    """

    def test_position_based_fallback_false_condition(self):
        """Position-based fallback should take second child for False condition."""
        workflow = {
            "inputs": [
                {
                    "id": "score",
                    "name": "Score",
                    "type": "number",
                    "range": {"min": 0, "max": 100}
                }
            ],
            "outputs": [
                {"name": "Pass", "description": "Score >= 50"},
                {"name": "Fail", "description": "Score < 50"}
            ],
            "tree": {
                "start": {
                    "id": "start",
                    "type": "start",
                    "label": "Start",
                    "children": [
                        {
                            "id": "score_check",
                            "type": "decision",
                            "label": "Score >= 50",
                            "input_ids": ["score"],
                            "condition": {
                                "input_id": "score",
                                "comparator": "gte",
                                "value": 50
                            },
                            "children": [
                                {
                                    # Position 0 = True branch
                                    "id": "out_pass",
                                    "type": "output",
                                    "label": "Pass",
                                    "children": []
                                },
                                {
                                    # Position 1 = False branch
                                    "id": "out_fail",
                                    "type": "output",
                                    "label": "Fail",
                                    "children": []
                                }
                            ]
                        }
                    ]
                }
            }
        }

        interpreter = TreeInterpreter(
            tree=workflow["tree"],
            inputs=workflow["inputs"],
            outputs=workflow["outputs"]
        )

        # Score = 40, condition "Score >= 50" is FALSE
        # Should take position 1 (False branch) -> "Fail"
        result = interpreter.execute({"score": 40})
        
        assert result.success is True
        assert result.output == "Fail", (
            f"Expected 'Fail' for Score=40, got '{result.output}'"
        )

    def test_position_based_fallback_true_condition(self):
        """Position-based fallback should take first child for True condition."""
        workflow = {
            "inputs": [
                {
                    "id": "score",
                    "name": "Score",
                    "type": "number",
                    "range": {"min": 0, "max": 100}
                }
            ],
            "outputs": [
                {"name": "Pass", "description": "Score >= 50"},
                {"name": "Fail", "description": "Score < 50"}
            ],
            "tree": {
                "start": {
                    "id": "start",
                    "type": "start",
                    "label": "Start",
                    "children": [
                        {
                            "id": "score_check",
                            "type": "decision",
                            "label": "Score >= 50",
                            "input_ids": ["score"],
                            "condition": {
                                "input_id": "score",
                                "comparator": "gte",
                                "value": 50
                            },
                            "children": [
                                {
                                    # Position 0 = True branch
                                    "id": "out_pass",
                                    "type": "output",
                                    "label": "Pass",
                                    "children": []
                                },
                                {
                                    # Position 1 = False branch
                                    "id": "out_fail",
                                    "type": "output",
                                    "label": "Fail",
                                    "children": []
                                }
                            ]
                        }
                    ]
                }
            }
        }

        interpreter = TreeInterpreter(
            tree=workflow["tree"],
            inputs=workflow["inputs"],
            outputs=workflow["outputs"]
        )

        # Score = 75, condition "Score >= 50" is TRUE
        # Should take position 0 (True branch) -> "Pass"
        result = interpreter.execute({"score": 75})
        
        assert result.success is True
        assert result.output == "Pass", (
            f"Expected 'Pass' for Score=75, got '{result.output}'"
        )


class TestAllComparatorsWithEmptyLabels:
    """Test all comparators work correctly when edge labels are empty."""

    @pytest.mark.parametrize("comparator,value,input_val,expected_branch", [
        # Less than tests
        ("lt", 50, 30, "True"),   # 30 < 50 = True
        ("lt", 50, 50, "False"),  # 50 < 50 = False
        ("lt", 50, 70, "False"),  # 70 < 50 = False
        
        # Greater than tests
        ("gt", 50, 70, "True"),   # 70 > 50 = True
        ("gt", 50, 50, "False"),  # 50 > 50 = False
        ("gt", 50, 30, "False"),  # 30 > 50 = False
        
        # Less than or equal tests
        ("lte", 50, 30, "True"),  # 30 <= 50 = True
        ("lte", 50, 50, "True"),  # 50 <= 50 = True
        ("lte", 50, 70, "False"), # 70 <= 50 = False
        
        # Greater than or equal tests
        ("gte", 50, 70, "True"),  # 70 >= 50 = True
        ("gte", 50, 50, "True"),  # 50 >= 50 = True
        ("gte", 50, 30, "False"), # 30 >= 50 = False
        
        # Equal tests
        ("eq", 50, 50, "True"),   # 50 == 50 = True
        ("eq", 50, 30, "False"),  # 30 == 50 = False
        
        # Not equal tests
        ("neq", 50, 30, "True"),  # 30 != 50 = True
        ("neq", 50, 50, "False"), # 50 != 50 = False
    ])
    def test_comparator_with_empty_labels(self, comparator, value, input_val, expected_branch):
        """Test each comparator takes correct branch with empty edge labels."""
        workflow = {
            "inputs": [
                {
                    "id": "num",
                    "name": "Number",
                    "type": "number",
                    "range": {"min": 0, "max": 100}
                }
            ],
            "outputs": [
                {"name": "True", "description": "Condition is true"},
                {"name": "False", "description": "Condition is false"}
            ],
            "tree": {
                "start": {
                    "id": "start",
                    "type": "start",
                    "label": "Start",
                    "children": [
                        {
                            "id": "check",
                            "type": "decision",
                            "label": f"num {comparator} {value}",
                            "input_ids": ["num"],
                            "condition": {
                                "input_id": "num",
                                "comparator": comparator,
                                "value": value
                            },
                            "children": [
                                {
                                    # Position 0 = True branch (no edge_label)
                                    "id": "out_true",
                                    "type": "output",
                                    "label": "True",
                                    "children": []
                                },
                                {
                                    # Position 1 = False branch (no edge_label)
                                    "id": "out_false",
                                    "type": "output",
                                    "label": "False",
                                    "children": []
                                }
                            ]
                        }
                    ]
                }
            }
        }

        interpreter = TreeInterpreter(
            tree=workflow["tree"],
            inputs=workflow["inputs"],
            outputs=workflow["outputs"]
        )

        result = interpreter.execute({"num": input_val})
        
        assert result.success is True, f"Execution failed: {result.error}"
        assert result.output == expected_branch, (
            f"Comparator {comparator}: {input_val} {comparator} {value} "
            f"expected '{expected_branch}', got '{result.output}'"
        )
