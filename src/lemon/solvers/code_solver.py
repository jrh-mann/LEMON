"""Agentic code generation solver (iterative refinement loop)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from ..core.solver import Solver, SolverIteration
from ..core.workflow import WorkflowAnalysis
from ..generation.generator import CodeGenerator, GenerationContext
from ..generation.validator import has_entrypoint_function
from ..testing.harness import TestHarness
from ..utils.logging import get_logger

logger = get_logger(__name__)


class AgenticCodeSolver(Solver):
    """Agentic solver that iteratively generates and refines Python code.
    
    This solver implements the "coding loop" strategy:
    1. Generate code from workflow analysis
    2. Test code against labeled test cases
    3. Analyze failures
    4. Refine code with failure context
    5. Repeat until 100% pass rate or max_iterations
    
    The loop runs inside solve(), and results are yielded after each iteration.
    """

    def __init__(
        self,
        *,
        workflow_image: Path,
        workflow_analysis: WorkflowAnalysis,
        valid_outputs: List[str],
        test_harness: TestHarness,
        code_generator: Optional[CodeGenerator] = None,
        output_path: Optional[Path] = None,
    ):
        """Initialize agentic code solver.
        
        Args:
            workflow_image: Path to workflow diagram image
            workflow_analysis: Structured workflow analysis
            valid_outputs: List of valid output values
            test_harness: Test harness for scoring code
            code_generator: Code generator (creates default if None)
            output_path: Where to save generated code (default: cwd/generated_code.py)
        """
        self.workflow_image = workflow_image
        self.workflow_analysis = workflow_analysis
        self.valid_outputs = valid_outputs
        self.test_harness = test_harness
        self.code_generator = code_generator or CodeGenerator()
        self.output_path = output_path or (Path.cwd() / "generated_code.py")
        self.logger = get_logger(__name__)

    def solve(
        self,
        test_cases: List[Dict[str, Any]],
        *,
        max_iterations: Optional[int] = None,
        score_threshold: float = 1.0,
        **kwargs: Any,
    ) -> Iterator[SolverIteration]:
        """Solve by iteratively generating and refining code.
        
        Args:
            test_cases: Test cases (used by harness; passed via constructor)
            max_iterations: Maximum iterations (None = no limit)
            score_threshold: Stop if score >= threshold (default: 1.0 = 100%)
            **kwargs: Ignored (for interface compatibility)
            
        Yields:
            SolverIteration after each refinement iteration
        """
        self.logger.info(
            "Starting agentic code solver",
            extra={
                "max_iterations": max_iterations,
                "score_threshold": score_threshold,
            },
        )

        failures: Optional[List[Dict[str, Any]]] = None
        iteration = 0
        best_score = 0.0

        while True:
            iteration += 1

            # Max iterations check
            if max_iterations is not None and iteration > max_iterations:
                self.logger.warning(
                    "Reached max iterations; stopping",
                    extra={"max_iterations": max_iterations, "iteration": iteration},
                )
                break

            self.logger.info("Code generation iteration", extra={"iteration": iteration})

            # Generate code
            ctx = GenerationContext(
                failures=failures,
                test_cases_file=Path.cwd() / "tests.json",
            )
            code = self.code_generator.generate(
                workflow_image_path=self.workflow_image,
                workflow_data=self.workflow_analysis,
                valid_outputs=self.valid_outputs,
                context=ctx,
            )

            # Validate code structure
            if not has_entrypoint_function(code):
                self.logger.warning(
                    "Generated code missing entrypoint; retrying",
                    extra={"iteration": iteration},
                )
                # Yield a failure iteration
                yield SolverIteration(
                    iteration=iteration,
                    score=best_score,  # Keep previous best
                    state=code,  # Still save the invalid code
                )
                continue

            # Save code
            self.output_path.write_text(code, encoding="utf-8")
            self.logger.info("Code saved", extra={"path": str(self.output_path)})

            # Test code
            self.logger.info("Testing code against test cases...")
            results = self.test_harness.score(code)
            score = results.pass_rate
            best_score = max(best_score, score)

            # Print formatted score
            status = "✓" if score == 1.0 else "⚠️" if score >= 0.9 else "❌"
            print(f"\n{status} Iteration {iteration}: {score*100:.1f}% ({results.passed}/{results.total} tests passed)")
            if results.failures:
                print(f"   Failures: {len(results.failures)}")

            self.logger.info(
                "Iteration score",
                extra={
                    "iteration": iteration,
                    "score": score,
                    "passed": results.passed,
                    "total": results.total,
                    "failures": len(results.failures),
                },
            )

            # Yield iteration result
            yield SolverIteration(
                iteration=iteration,
                score=score,
                state=code,  # State is the generated code
                predictions=None,  # Could extract predictions from results if needed
            )

            # Early stopping: perfect score
            if score >= score_threshold:
                self.logger.info(
                    "Perfect score achieved; stopping",
                    extra={"iteration": iteration, "score": score},
                )
                break

            # Collect failures for next iteration
            self.logger.info(
                f"Collecting {len(results.failures)} failures for next iteration"
            )
            failures = [{"error": f.error, "test_case": f.test_case} for f in results.failures]

