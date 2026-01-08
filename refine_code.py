"""Steps 3-4: Code refinement loop + final validation.

Assumes steps 1-2 have already been run (workflow analysis + test generation).
Loads existing artifacts and runs the solver to generate/refine code.

Usage:
    uv run python refine_code.py --workflow-image workflow.jpeg --max-iterations 5
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.lemon.core.evaluator import SolverEvaluator
from src.lemon.core.solver import SolverIteration
from src.lemon.core.workflow import WorkflowAnalysis
from src.lemon.generation.generator import CodeGenerator
from src.lemon.solvers.code_solver import AgenticCodeSolver
from src.lemon.testing.harness import TestHarness
from src.lemon.testing.generator import TestCaseGenerator
from src.lemon.utils.logging import configure_logging, get_logger


@dataclass
class RefinementResult:
    """Result from code refinement (steps 3-4)."""

    code: str
    best_score: float
    iterations: int
    final_validation_pass_rate: Optional[float] = None


def load_prerequisites(base_dir: Path) -> tuple[list[str], WorkflowAnalysis, list[dict]]:
    """Load workflow analysis, outputs, and labeled test cases from steps 1-2."""
    logger = get_logger(__name__)

    # Load workflow analysis
    analysis_file = base_dir / "workflow_analysis.json"
    outputs_file = base_dir / "workflow_outputs.json"
    tests_file = base_dir / "tests.json"

    if not analysis_file.exists():
        raise FileNotFoundError(
            f"Missing {analysis_file}. Run steps 1-2 first (main.py or refine_workflow_code.py)."
        )
    if not outputs_file.exists():
        raise FileNotFoundError(
            f"Missing {outputs_file}. Run steps 1-2 first (main.py or refine_workflow_code.py)."
        )
    if not tests_file.exists():
        raise FileNotFoundError(
            f"Missing {tests_file}. Run steps 1-2 first (main.py or refine_workflow_code.py)."
        )

    logger.info("Loading workflow analysis and test cases...")
    valid_outputs = json.loads(outputs_file.read_text(encoding="utf-8"))
    analysis = WorkflowAnalysis.model_validate_json(
        analysis_file.read_text(encoding="utf-8")
    )
    labeled_tests = json.loads(tests_file.read_text(encoding="utf-8"))

    logger.info(
        "Prerequisites loaded",
        extra={
            "inputs": len(analysis.inputs),
            "outputs": len(valid_outputs),
            "test_cases": len(labeled_tests),
        },
    )

    return valid_outputs, analysis, labeled_tests


def run_final_validation(
    *,
    base_dir: Path,
    workflow_image: Path,
    valid_outputs: list[str],
    code: str,
    analysis: WorkflowAnalysis,
) -> float:
    """Run final validation with edge case tests (step 4)."""
    logger = get_logger(__name__)

    final_tests_file = base_dir / "final_tests.json"
    if final_tests_file.exists():
        logger.info("Loading cached final test cases")
        final_labeled = json.loads(final_tests_file.read_text(encoding="utf-8"))
    else:
        logger.info("Generating 200 edge case tests...")
        generator = TestCaseGenerator(str(base_dir / "workflow_inputs.json"))
        final_tests = generator.generate_test_cases(200, "edge_cases")
        logger.info("Labeling edge case tests...")
        final_labeled = generator.label_test_cases(
            test_cases=final_tests,
            workflow_image_path=str(workflow_image),
            valid_outputs=valid_outputs,
            workflow_analysis=analysis.model_dump(),
        )
        final_tests_file.write_text(json.dumps(final_labeled, indent=2), encoding="utf-8")
        logger.info("Final test cases saved", extra={"file": str(final_tests_file)})

    logger.info("Running final validation tests...", extra={"count": len(final_labeled)})
    final_harness = TestHarness(test_cases=final_labeled, valid_outputs=valid_outputs)
    final_score = final_harness.score(code)
    logger.info(
        "Final validation score",
        extra={
            "pass_rate": final_score.pass_rate,
            "passed": final_score.passed,
            "total": final_score.total,
        },
    )
    return final_score.pass_rate


def main() -> None:
    configure_logging(level="INFO", json_logs=False)
    logger = get_logger(__name__)

    parser = argparse.ArgumentParser(
        description="Steps 3-4: Iterative code refinement + final validation. "
        "Requires workflow_analysis.json, workflow_outputs.json, and tests.json from steps 1-2."
    )
    parser.add_argument("--workflow-image", type=str, default="workflow.jpeg")
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--skip-final-validation", action="store_true", help="Skip step 4 (final validation)")
    args = parser.parse_args()

    base_dir = Path.cwd()
    workflow_image = Path(args.workflow_image)

    # Load prerequisites from steps 1-2
    valid_outputs, analysis, labeled_tests = load_prerequisites(base_dir)

    # Step 3: Create solver and run refinement loop
    logger.info("Starting code refinement (step 3)...")
    harness = TestHarness(test_cases=labeled_tests, valid_outputs=valid_outputs)

    solver = AgenticCodeSolver(
        workflow_image=workflow_image,
        workflow_analysis=analysis,
        valid_outputs=valid_outputs,
        test_harness=harness,
        code_generator=CodeGenerator(),
        output_path=base_dir / "generated_code.py",
    )

    # Track best score for logging
    best_score = 0.0

    def on_iteration(iteration_result: SolverIteration) -> None:
        """Progress callback for solver iterations."""
        nonlocal best_score
        best_score = max(best_score, iteration_result.score)
        logger.info(
            f"Iteration {iteration_result.iteration}: {iteration_result.score*100:.1f}% "
            f"(best: {best_score*100:.1f}%)"
        )

    evaluator = SolverEvaluator(
        score_threshold=1.0,  # Stop at 100%
        max_iterations=args.max_iterations,
        on_iteration=on_iteration,
    )

    evaluation_result = evaluator.evaluate(
        solver=solver,
        test_cases=labeled_tests,  # Passed to solver via harness
        max_iterations=args.max_iterations,
        score_threshold=1.0,
    )

    code = evaluation_result.final_state or ""
    best_score = evaluation_result.best_score

    logger.info(
        "Step 3 complete",
        extra={
            "best_score": best_score,
            "iterations": evaluation_result.total_iterations,
            "code_length": len(code),
        },
    )

    # Step 4: Final validation (optional)
    final_validation_pass_rate = None
    if not args.skip_final_validation and best_score == 1.0:
        logger.info("Starting final validation (step 4)...")
        final_validation_pass_rate = run_final_validation(
            base_dir=base_dir,
            workflow_image=workflow_image,
            valid_outputs=valid_outputs,
            code=code,
            analysis=analysis,
        )
        logger.info(
            "Step 4 complete",
            extra={"final_validation_pass_rate": final_validation_pass_rate},
        )

    result = RefinementResult(
        code=code,
        best_score=best_score,
        iterations=evaluation_result.total_iterations,
        final_validation_pass_rate=final_validation_pass_rate,
    )

    logger.info(
        "Refinement complete",
        extra={
            "best_score": result.best_score,
            "iterations": result.iterations,
            "final_validation_pass_rate": result.final_validation_pass_rate,
            "generated_code_path": str(base_dir / "generated_code.py"),
        },
    )


if __name__ == "__main__":
    main()

