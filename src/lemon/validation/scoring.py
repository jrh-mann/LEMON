"""Validation scoring and confidence calculation.

This module calculates validation scores from human answers and
determines confidence levels based on sample size.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from lemon.validation.session import ValidationAnswer


ConfidenceLevel = Literal["none", "low", "medium", "high"]


@dataclass
class ValidationScore:
    """Score from a validation session."""
    matches: int
    total: int

    @property
    def score(self) -> float:
        """Get score as percentage (0-100)."""
        if self.total == 0:
            return 0.0
        return (self.matches / self.total) * 100

    @property
    def confidence(self) -> ConfidenceLevel:
        """Get confidence level based on total validations."""
        return calculate_confidence(self.total)

    @property
    def is_validated(self) -> bool:
        """Whether this meets validation threshold.

        Validated means:
        - Score >= 80%
        - At least medium confidence (10+ validations)
        """
        return self.score >= 80.0 and self.total >= 10

    def to_dict(self) -> dict:
        return {
            "matches": self.matches,
            "total": self.total,
            "score": self.score,
            "confidence": self.confidence,
            "is_validated": self.is_validated,
        }


def calculate_score(answers: List["ValidationAnswer"]) -> ValidationScore:
    """Calculate validation score from answers.

    Args:
        answers: List of validation answers.

    Returns:
        ValidationScore with matches and total.
    """
    if not answers:
        return ValidationScore(matches=0, total=0)

    matches = sum(1 for a in answers if a.matched)
    return ValidationScore(matches=matches, total=len(answers))


def calculate_confidence(total_validations: int) -> ConfidenceLevel:
    """Calculate confidence level from validation count.

    Confidence levels:
    - none: 0 validations
    - low: 1-9 validations
    - medium: 10-49 validations
    - high: 50+ validations

    Args:
        total_validations: Number of completed validations.

    Returns:
        Confidence level string.
    """
    if total_validations == 0:
        return "none"
    elif total_validations < 10:
        return "low"
    elif total_validations < 50:
        return "medium"
    else:
        return "high"


def combine_scores(
    parent_score: ValidationScore,
    child_scores: List[ValidationScore],
    parent_weight: float = 0.5,
) -> ValidationScore:
    """Combine scores for composed workflows.

    A composed workflow's score is influenced by:
    - Its own direct validation score
    - The scores of referenced child workflows

    Args:
        parent_score: The direct validation score.
        child_scores: Scores from referenced workflows.
        parent_weight: Weight for parent vs children (0-1).

    Returns:
        Combined ValidationScore.
    """
    if not child_scores:
        return parent_score

    # Calculate child weighted average
    total_child_matches = sum(s.matches for s in child_scores)
    total_child_total = sum(s.total for s in child_scores)

    if total_child_total == 0:
        return parent_score

    child_rate = total_child_matches / total_child_total

    # Calculate parent rate
    if parent_score.total == 0:
        parent_rate = 0.0
    else:
        parent_rate = parent_score.matches / parent_score.total

    # Combine
    combined_rate = parent_weight * parent_rate + (1 - parent_weight) * child_rate
    combined_total = parent_score.total + total_child_total

    # Convert back to matches/total format
    combined_matches = int(combined_rate * combined_total)

    return ValidationScore(
        matches=combined_matches,
        total=combined_total,
    )
