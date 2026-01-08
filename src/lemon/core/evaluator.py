"""Evaluator for scoring solver results.

The evaluator is a thin wrapper that:
- Calls solver.solve() and collects yielded results
- Tracks best iteration
- Supports early stopping based on score threshold
- Returns evaluation summary
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from .solver import Solver, SolverIteration
from ..utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class EvaluationResult:
    """Final evaluation result from running a solver."""

    best_iteration: int
    best_score: float
    total_iterations: int
    final_state: Any  # Solver-specific final state
    all_iterations: List[SolverIteration]  # All yielded iterations


class SolverEvaluator:
    """Evaluates a solver by running it and collecting results.
    
    The evaluator is solver-agnostic: it doesn't know or care how the solver
    works internally (code generation loop, ML model, etc.). It just:
    1. Calls solver.solve()
    2. Collects yielded results
    3. Tracks best score
    4. Optionally stops early based on threshold
    """

    def __init__(
        self,
        *,
        score_threshold: Optional[float] = None,
        max_iterations: Optional[int] = None,
        on_iteration: Optional[Callable[[SolverIteration], None]] = None,
    ):
        """Initialize evaluator.
        
        Args:
            score_threshold: Stop early if score >= threshold (None = no early stop)
            max_iterations: Maximum iterations to allow (None = no limit)
            on_iteration: Optional callback called after each iteration
        """
        self.score_threshold = score_threshold
        self.max_iterations = max_iterations
        self.on_iteration = on_iteration
        self.logger = get_logger(__name__)

    def evaluate(
        self,
        solver: Solver,
        test_cases: List[Dict[str, Any]],
        **solver_kwargs: Any,
    ) -> EvaluationResult:
        """Run solver and evaluate results.
        
        Args:
            solver: Solver to evaluate
            test_cases: Test cases to solve
            **solver_kwargs: Additional arguments passed to solver.solve()
            
        Returns:
            EvaluationResult with best score and all iterations
        """
        self.logger.info(
            "Starting solver evaluation",
            extra={
                "num_test_cases": len(test_cases),
                "score_threshold": self.score_threshold,
                "max_iterations": self.max_iterations,
            },
        )

        all_iterations: List[SolverIteration] = []
        best_score = 0.0
        best_iteration = 0
        final_state = None

        # Run solver (it's a generator)
        for iteration_result in solver.solve(test_cases, **solver_kwargs):
            all_iterations.append(iteration_result)
            final_state = iteration_result.state

            # Print iteration summary (scores are already printed by solver)
            if iteration_result.score >= self.score_threshold:
                print(f"✓ Reached score threshold ({self.score_threshold*100:.1f}%)")

            self.logger.info(
                "Solver iteration",
                extra={
                    "iteration": iteration_result.iteration,
                    "score": iteration_result.score,
                },
            )

            # Track best
            if iteration_result.score > best_score:
                best_score = iteration_result.score
                best_iteration = iteration_result.iteration

            # Call progress callback if provided
            if self.on_iteration:
                self.on_iteration(iteration_result)

            # Early stopping: score threshold
            if (
                self.score_threshold is not None
                and iteration_result.score >= self.score_threshold
            ):
                self.logger.info(
                    "Early stopping: score threshold reached",
                    extra={
                        "iteration": iteration_result.iteration,
                        "score": iteration_result.score,
                        "threshold": self.score_threshold,
                    },
                )
                break

            # Early stopping: max iterations
            if (
                self.max_iterations is not None
                and len(all_iterations) >= self.max_iterations
            ):
                self.logger.info(
                    "Early stopping: max iterations reached",
                    extra={
                        "iterations": len(all_iterations),
                        "max_iterations": self.max_iterations,
                    },
                )
                break

        self.logger.info(
            "Solver evaluation complete",
            extra={
                "total_iterations": len(all_iterations),
                "best_score": best_score,
                "best_iteration": best_iteration,
            },
        )

        return EvaluationResult(
            best_iteration=best_iteration,
            best_score=best_score,
            total_iterations=len(all_iterations),
            final_state=final_state,
            all_iterations=all_iterations,
        )

