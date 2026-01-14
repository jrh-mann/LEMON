"""Tests for validation scoring."""

import pytest
from datetime import datetime, timezone
from lemon.validation.scoring import (
    ValidationScore,
    calculate_score,
    calculate_confidence,
    combine_scores,
)
from lemon.validation.session import ValidationAnswer


# -----------------------------------------------------------------------------
# Test: ValidationScore
# -----------------------------------------------------------------------------

class TestValidationScore:
    """Tests for ValidationScore dataclass."""

    def test_score_calculation(self):
        """Should calculate score as percentage."""
        score = ValidationScore(matches=8, total=10)
        assert score.score == 80.0

    def test_score_zero_total(self):
        """Should handle zero total gracefully."""
        score = ValidationScore(matches=0, total=0)
        assert score.score == 0.0

    def test_score_perfect(self):
        """Should calculate perfect score."""
        score = ValidationScore(matches=100, total=100)
        assert score.score == 100.0

    def test_score_none(self):
        """Should calculate zero score."""
        score = ValidationScore(matches=0, total=50)
        assert score.score == 0.0

    def test_to_dict(self):
        """Should serialize to dictionary."""
        score = ValidationScore(matches=15, total=20)
        result = score.to_dict()

        assert result["matches"] == 15
        assert result["total"] == 20
        assert result["score"] == 75.0
        assert result["confidence"] == "medium"
        assert result["is_validated"] is False


# -----------------------------------------------------------------------------
# Test: Confidence Levels
# -----------------------------------------------------------------------------

class TestConfidenceLevels:
    """Tests for confidence level calculation."""

    def test_confidence_none(self):
        """Zero validations should have no confidence."""
        assert calculate_confidence(0) == "none"

        score = ValidationScore(matches=0, total=0)
        assert score.confidence == "none"

    def test_confidence_low(self):
        """1-9 validations should have low confidence."""
        for n in [1, 5, 9]:
            assert calculate_confidence(n) == "low"

        score = ValidationScore(matches=5, total=9)
        assert score.confidence == "low"

    def test_confidence_medium(self):
        """10-49 validations should have medium confidence."""
        for n in [10, 25, 49]:
            assert calculate_confidence(n) == "medium"

        score = ValidationScore(matches=40, total=49)
        assert score.confidence == "medium"

    def test_confidence_high(self):
        """50+ validations should have high confidence."""
        for n in [50, 100, 1000]:
            assert calculate_confidence(n) == "high"

        score = ValidationScore(matches=45, total=50)
        assert score.confidence == "high"


# -----------------------------------------------------------------------------
# Test: Validation Threshold
# -----------------------------------------------------------------------------

class TestValidationThreshold:
    """Tests for validation threshold (is_validated)."""

    def test_validated_requires_score_and_count(self):
        """Should require both 80% score and 10+ validations."""
        # 80% but only 9 validations
        score1 = ValidationScore(matches=8, total=9)
        assert score1.is_validated is False

        # 10 validations but only 70%
        score2 = ValidationScore(matches=7, total=10)
        assert score2.is_validated is False

        # Both conditions met
        score3 = ValidationScore(matches=8, total=10)
        assert score3.is_validated is True

    def test_validated_exact_threshold(self):
        """Should validate at exactly 80% with 10 validations."""
        score = ValidationScore(matches=8, total=10)
        assert score.score == 80.0
        assert score.is_validated is True

    def test_validated_above_threshold(self):
        """Should validate above threshold."""
        score = ValidationScore(matches=95, total=100)
        assert score.is_validated is True

    def test_not_validated_below_threshold(self):
        """Should not validate below threshold."""
        # Just below 80%
        score = ValidationScore(matches=79, total=100)
        assert score.is_validated is False


# -----------------------------------------------------------------------------
# Test: Calculate Score from Answers
# -----------------------------------------------------------------------------

class TestCalculateScore:
    """Tests for calculate_score function."""

    def test_empty_answers(self):
        """Should handle empty answer list."""
        score = calculate_score([])
        assert score.matches == 0
        assert score.total == 0

    def test_all_matches(self):
        """Should count all matches."""
        answers = [
            ValidationAnswer(
                case_id=f"case{i}",
                user_answer="yes",
                workflow_output="yes",
                matched=True,
            )
            for i in range(10)
        ]
        score = calculate_score(answers)
        assert score.matches == 10
        assert score.total == 10
        assert score.score == 100.0

    def test_no_matches(self):
        """Should count zero matches."""
        answers = [
            ValidationAnswer(
                case_id=f"case{i}",
                user_answer="yes",
                workflow_output="no",
                matched=False,
            )
            for i in range(10)
        ]
        score = calculate_score(answers)
        assert score.matches == 0
        assert score.total == 10
        assert score.score == 0.0

    def test_mixed_results(self):
        """Should count mixed results correctly."""
        answers = [
            ValidationAnswer(case_id="c1", user_answer="a", workflow_output="a", matched=True),
            ValidationAnswer(case_id="c2", user_answer="b", workflow_output="b", matched=True),
            ValidationAnswer(case_id="c3", user_answer="x", workflow_output="y", matched=False),
            ValidationAnswer(case_id="c4", user_answer="c", workflow_output="c", matched=True),
            ValidationAnswer(case_id="c5", user_answer="z", workflow_output="w", matched=False),
        ]
        score = calculate_score(answers)
        assert score.matches == 3
        assert score.total == 5
        assert score.score == 60.0


# -----------------------------------------------------------------------------
# Test: Combine Scores
# -----------------------------------------------------------------------------

class TestCombineScores:
    """Tests for combine_scores function."""

    def test_no_children(self):
        """Should return parent score when no children."""
        parent = ValidationScore(matches=8, total=10)
        result = combine_scores(parent, [])
        assert result.matches == 8
        assert result.total == 10

    def test_combine_with_children(self):
        """Should combine parent and child scores."""
        parent = ValidationScore(matches=8, total=10)
        children = [
            ValidationScore(matches=9, total=10),
            ValidationScore(matches=7, total=10),
        ]
        result = combine_scores(parent, children, parent_weight=0.5)

        # Parent: 80%, Children: 80% average
        # Combined: 50% * 80% + 50% * 80% = 80%
        # Total: 10 + 20 = 30
        assert result.total == 30
        # Combined rate ~0.8, so matches ~24
        assert result.matches == 24

    def test_parent_weight_full(self):
        """Should use only parent score when weight is 1.0."""
        parent = ValidationScore(matches=10, total=10)
        children = [ValidationScore(matches=0, total=10)]

        result = combine_scores(parent, children, parent_weight=1.0)
        # 100% * 1.0 + 0% * 0.0 = 100%
        assert result.total == 20
        assert result.matches == 20

    def test_child_weight_full(self):
        """Should use only child scores when parent weight is 0.0."""
        parent = ValidationScore(matches=0, total=10)
        children = [ValidationScore(matches=10, total=10)]

        result = combine_scores(parent, children, parent_weight=0.0)
        # 0% * 0.0 + 100% * 1.0 = 100%
        assert result.total == 20
        assert result.matches == 20

    def test_empty_children_total(self):
        """Should handle children with zero total."""
        parent = ValidationScore(matches=8, total=10)
        children = [ValidationScore(matches=0, total=0)]

        result = combine_scores(parent, children)
        # Should return parent score
        assert result.matches == 8
        assert result.total == 10

    def test_empty_parent_total(self):
        """Should handle parent with zero total."""
        parent = ValidationScore(matches=0, total=0)
        children = [ValidationScore(matches=8, total=10)]

        result = combine_scores(parent, children, parent_weight=0.5)
        # Parent rate: 0.0, Child rate: 0.8
        # Combined: 0.5 * 0 + 0.5 * 0.8 = 0.4
        # Total: 0 + 10 = 10
        assert result.total == 10
        assert result.matches == 4

    def test_multiple_children(self):
        """Should combine multiple children correctly."""
        parent = ValidationScore(matches=5, total=10)  # 50%
        children = [
            ValidationScore(matches=8, total=10),   # 80%
            ValidationScore(matches=6, total=10),   # 60%
            ValidationScore(matches=10, total=10),  # 100%
        ]
        # Child average: (8+6+10) / 30 = 24/30 = 80%
        # Combined with 50% weight: 0.5 * 50% + 0.5 * 80% = 65%
        # Total: 10 + 30 = 40
        result = combine_scores(parent, children, parent_weight=0.5)

        assert result.total == 40
        assert result.matches == 26  # 65% of 40
