"""Abstract solver interface for workflow problem solving.

Solvers are systems that take test cases and produce outputs. They can be:
- Agentic code generation loops (iterative refinement)
- ML models (single-shot prediction)
- Rule-based systems
- etc.

The key abstraction is that solvers yield results over time, allowing for:
- Progress tracking
- Early stopping
- Different iteration strategies per solver type
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional


@dataclass(frozen=True)
class SolverIteration:
    """Result from a single solver iteration."""

    iteration: int
    score: float
    state: Any  # Solver-specific state (code string, model, predictions, etc.)
    predictions: Optional[List[str]] = None  # Optional: predicted outputs for each test case


class Solver(ABC):
    """Abstract base class for workflow solvers.
    
    Solvers implement the core problem-solving logic. They can be:
    - Iterative (e.g., agentic code refinement loops)
    - Single-shot (e.g., trained ML models)
    
    The solve() method is a generator that yields SolverIteration results,
    allowing the caller to observe progress and implement early stopping.
    """

    @abstractmethod
    def solve(
        self,
        test_cases: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> Iterator[SolverIteration]:
        """Solve the workflow problem.
        
        Args:
            test_cases: List of test case dictionaries with inputs
            **kwargs: Solver-specific parameters (max_iterations, threshold, etc.)
            
        Yields:
            SolverIteration: Results after each iteration
            
        Example:
            # Agentic code solver (yields multiple times)
            for result in solver.solve(test_cases, max_iterations=10):
                if result.score >= 0.99:
                    break
                    
            # XGBoost solver (yields once)
            for result in solver.solve(test_cases):
                # Only one iteration
                break
        """
        raise NotImplementedError

