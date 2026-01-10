"""Pipeline orchestration for LEMON."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..analysis.agent import WorkflowAnalyzer
from ..config.settings import Settings
from ..core.evaluator import SolverEvaluator
from ..core.solver import SolverIteration
from ..core.workflow import StandardizedInput, WorkflowAnalysis
from ..generation.generator import CodeGenerator
from ..solvers.code_solver import AgenticCodeSolver
from ..testing.generator import TestCaseGenerator
from ..testing.harness import TestHarness
from ..utils.logging import get_logger


@dataclass(frozen=True)
class PipelineResult:
    """High-level pipeline result."""

    code: str
    generated_code_path: Path
    pass_rate: float
    iterations: int
    best_pass_rate: float
    final_validation_pass_rate: Optional[float] = None


class RefinementPipeline:
    """Orchestrates workflow analysis, test generation, codegen, and validation.

    This is intentionally a thin shell for now; later todos will migrate all logic here.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        progress_callback: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
    ):
        self.settings = settings
        self.logger = get_logger(__name__)
        self._progress_callback = progress_callback
        self.analyzer = WorkflowAnalyzer(max_tokens=64000)
        # Don't create test_generator here - it requires workflow_inputs.json which doesn't exist yet
        # It will be created when needed in _load_or_generate_tests
        self.code_generator = CodeGenerator()

    def _emit(self, stage: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        if self._progress_callback:
            self._progress_callback(stage, message, data or {})

    def run(self, workflow_image: Path) -> PipelineResult:
        """Run the pipeline until convergence (100% pass rate)."""
        return self.run_with_options(workflow_image=workflow_image, max_iterations=None)

    def run_with_options(
        self,
        *,
        workflow_image: Path,
        max_iterations: Optional[int],
        num_test_cases: int = 1000,
        num_final_validation_tests: int = 200,
        batch_size: int = 20,
        max_workers: int = 5,
        best_of_n: int = 3,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        backoff_cap: float = 8.0,
        log_responses: bool = False,
    ) -> PipelineResult:
        """Run the pipeline with optional iteration cap."""
        base_dir = Path.cwd()

        self._emit("setup", "Starting pipeline...", {"workflow_image": str(workflow_image)})
        valid_outputs, analysis = self._load_or_analyze(
            base_dir=base_dir, workflow_image=workflow_image
        )
        labeled_tests = self._load_or_generate_tests(
            base_dir=base_dir,
            workflow_image=workflow_image,
            valid_outputs=valid_outputs,
            analysis=analysis,
            num_test_cases=num_test_cases,
            batch_size=batch_size,
            max_workers=max_workers,
            best_of_n=best_of_n,
            max_retries=max_retries,
            backoff_base=backoff_base,
            backoff_cap=backoff_cap,
            log_responses=log_responses,
        )

        harness = TestHarness(test_cases=labeled_tests, valid_outputs=valid_outputs)

        # Create solver (contains the refinement loop)
        solver = AgenticCodeSolver(
            workflow_image=workflow_image,
            workflow_analysis=analysis,
            valid_outputs=valid_outputs,
            test_harness=harness,
            code_generator=self.code_generator,
            output_path=base_dir / "generated_code.py",
        )

        # Track best score for progress callbacks
        best_score = 0.0

        def on_iteration(iteration_result: SolverIteration) -> None:
            """Progress callback for solver iterations."""
            nonlocal best_score
            best_score = max(best_score, iteration_result.score)

            self._emit(
                "refinement",
                f"🔄 Iteration {iteration_result.iteration} (best: {best_score*100:.1f}%)",
                {
                    "iteration": iteration_result.iteration,
                    "best_pass_rate": best_score,
                    "current_score": iteration_result.score,
                },
            )

            # Emit code generation progress
            if iteration_result.state:  # state is the generated code
                self._emit(
                    "code_generation",
                    "✓ Code generated and saved",
                    {"code": iteration_result.state},
                )

            # Emit testing progress
            status_emoji = "✓" if iteration_result.score == 1.0 else "⚠️" if iteration_result.score >= 0.9 else "❌"
            self._emit(
                "testing",
                f"{status_emoji} Score: {iteration_result.score*100:.1f}%",
                {
                    "score": iteration_result.score,
                    "iteration": iteration_result.iteration,
                },
            )

            if iteration_result.score == 1.0:
                self._emit("refinement", "✓ 100% pass rate achieved!")

        # Create evaluator (thin wrapper that runs solver and collects results)
        evaluator = SolverEvaluator(
            score_threshold=1.0,  # Stop at 100%
            max_iterations=max_iterations,
            on_iteration=on_iteration,
        )

        self.logger.info("Starting solver evaluation")
        self._emit("setup", "Starting refinement solver...")

        # Run solver via evaluator
        evaluation_result = evaluator.evaluate(
            solver=solver,
            test_cases=labeled_tests,  # Passed to solver via harness
            max_iterations=max_iterations,
            score_threshold=1.0,
        )

        # Extract final code from evaluation result
        code = evaluation_result.final_state or ""
        best = evaluation_result.best_score

        # Print solver evaluation summary
        print(f"\n📊 Solver Evaluation Summary:")
        print(f"   Iterations: {evaluation_result.total_iterations}")
        print(f"   Best Score: {best*100:.1f}%")
        print(f"   Best Iteration: {evaluation_result.best_iteration}")
        if best == 1.0:
            print(f"   ✓ Achieved 100% pass rate!")

        final_validation_pass_rate = None
        if best == 1.0:
            self.logger.info("Starting final validation with edge cases")
            self._emit("final_validation", "🎯 Final validation (edge cases)...")
            final_validation_pass_rate = self._final_validation(
                base_dir=base_dir,
                workflow_image=workflow_image,
                valid_outputs=valid_outputs,
                code=code,
                analysis=analysis,
                num_final_validation_tests=num_final_validation_tests,
                batch_size=batch_size,
                max_workers=max_workers,
                best_of_n=best_of_n,
                max_retries=max_retries,
                backoff_base=backoff_base,
                backoff_cap=backoff_cap,
                log_responses=log_responses,
            )
            validation_emoji = "✓" if final_validation_pass_rate == 1.0 else "⚠️" if final_validation_pass_rate >= 0.9 else "❌"
            self.logger.info("Final validation complete", extra={"pass_rate": final_validation_pass_rate})
            self._emit(
                "final_validation",
                f"{validation_emoji} Final validation: {final_validation_pass_rate*100:.1f}%",
                {"final_score": final_validation_pass_rate},
            )

        return PipelineResult(
            code=code,
            generated_code_path=base_dir / "generated_code.py",
            pass_rate=(harness.score(code).pass_rate if code else 0.0),
            iterations=evaluation_result.total_iterations,
            best_pass_rate=best,
            final_validation_pass_rate=final_validation_pass_rate,
        )

    def _load_or_analyze(
        self, *, base_dir: Path, workflow_image: Path
    ) -> Tuple[List[str], WorkflowAnalysis]:
        inputs_file = base_dir / "workflow_inputs.json"
        outputs_file = base_dir / "workflow_outputs.json"
        analysis_file = base_dir / "workflow_analysis.json"

        if analysis_file.exists() and outputs_file.exists():
            self.logger.info("Loading cached workflow analysis")
            self._emit("analysis", "✓ Found existing analysis; loading cached files")
            valid_outputs = json.loads(outputs_file.read_text(encoding="utf-8"))
            analysis = WorkflowAnalysis.model_validate_json(
                analysis_file.read_text(encoding="utf-8")
            )
            self.logger.info("Workflow analysis loaded", extra={"inputs": len(analysis.inputs), "outputs": len(valid_outputs)})
            return valid_outputs, analysis

        self.logger.info("Starting workflow analysis...", extra={"workflow_image": str(workflow_image)})
        self._emit("analysis", "📸 Analyzing workflow structure...")
        
        # Stream workflow analysis to stdout if running in CLI mode
        def stream_callback(chunk: str) -> None:
            """Print analysis chunks as they arrive."""
            import sys
            sys.stdout.write(chunk)
            sys.stdout.flush()
        
        analysis = self.analyzer.analyze(workflow_image, stream_callback=stream_callback)
        print()  # New line after streaming
        self.logger.info("Workflow analysis complete")
        standardized_inputs: List[StandardizedInput] = self.analyzer.extract_standardized_inputs(
            analysis
        )
        valid_outputs = self.analyzer.extract_outputs(analysis)

        self.logger.info("Saving workflow analysis files...")
        analysis_file.write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
        inputs_file.write_text(
            json.dumps([x.model_dump() for x in standardized_inputs], indent=2), encoding="utf-8"
        )
        outputs_file.write_text(json.dumps(valid_outputs, indent=2), encoding="utf-8")

        self.logger.info("Workflow analysis saved", extra={
            "analysis_file": str(analysis_file),
            "inputs_file": str(inputs_file),
            "outputs_file": str(outputs_file)
        })
        self._emit(
            "analysis",
            f"✓ Analysis complete: {len(standardized_inputs)} inputs, {len(valid_outputs)} outputs",
            {"inputs": len(standardized_inputs), "outputs": len(valid_outputs)},
        )
        return valid_outputs, analysis

    def _load_or_generate_tests(
        self,
        *,
        base_dir: Path,
        workflow_image: Path,
        valid_outputs: List[str],
        analysis: WorkflowAnalysis,
        num_test_cases: int = 1000,
        batch_size: int = 20,
        max_workers: int = 5,
        best_of_n: int = 3,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        backoff_cap: float = 8.0,
        log_responses: bool = False,
    ) -> List[Dict[str, Any]]:
        tests_file = base_dir / "tests.json"
        if tests_file.exists():
            self.logger.info("Loading cached test cases")
            self._emit("test_generation", "✓ Found existing test cases; loading cached file")
            cached = json.loads(tests_file.read_text(encoding="utf-8"))
            labeled_count = len([t for t in cached if t.get('expected_output') is not None])
            self.logger.info("Test cases loaded", extra={"total": len(cached), "labeled": labeled_count})
            return cached if isinstance(cached, list) else []

        self.logger.info("Generating test cases...", extra={"count": num_test_cases, "strategy": "comprehensive"})
        self._emit("test_generation", f"🎲 Generating {num_test_cases} initial test cases...")
        generator = TestCaseGenerator(str(base_dir / "workflow_inputs.json"))
        test_cases = generator.generate_test_cases(num_test_cases, "comprehensive")
        self.logger.info("Test cases generated", extra={"count": len(test_cases)})
        
        # Save unlabeled test cases immediately after generation
        unlabeled_tests_file = base_dir / "test_cases.json"
        unlabeled_tests_file.write_text(json.dumps(test_cases, indent=2), encoding="utf-8")
        self.logger.info("Unlabeled test cases saved", extra={"file": str(unlabeled_tests_file), "count": len(test_cases)})
        
        self.logger.info("Labeling test cases with workflow analysis context...")
        self._emit("test_generation", "🏷️ Labeling test cases (this may take a few minutes)...")
        labeled = generator.label_test_cases(
            test_cases=test_cases,
            workflow_image_path=str(workflow_image),
            valid_outputs=valid_outputs,
            workflow_analysis=analysis.model_dump(),
            batch_size=batch_size,
            max_workers=max_workers,
            best_of_n=best_of_n,
            max_retries=max_retries,
            backoff_base=backoff_base,
            backoff_cap=backoff_cap,
            log_responses=log_responses,
        )
        self.logger.info("Test cases labeled", extra={"count": len(labeled)})
        
        tests_file.write_text(json.dumps(labeled, indent=2), encoding="utf-8")
        self.logger.info("Test cases saved", extra={"file": str(tests_file)})
        self._emit("test_generation", f"✓ {len(labeled)} test cases generated and labeled", {"count": len(labeled)})
        return labeled

    def _final_validation(
        self,
        *,
        base_dir: Path,
        workflow_image: Path,
        valid_outputs: List[str],
        code: str,
        analysis: WorkflowAnalysis,
        num_final_validation_tests: int = 200,
        batch_size: int = 20,
        max_workers: int = 5,
        best_of_n: int = 3,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        backoff_cap: float = 8.0,
        log_responses: bool = False,
    ) -> float:
        final_tests_file = base_dir / "final_tests.json"
        if final_tests_file.exists():
            self.logger.info("Loading cached final test cases")
            final_labeled = json.loads(final_tests_file.read_text(encoding="utf-8"))
        else:
            self.logger.info(f"Generating {num_final_validation_tests} edge case tests...")
            generator = TestCaseGenerator(str(base_dir / "workflow_inputs.json"))
            final_tests = generator.generate_test_cases(num_final_validation_tests, "edge_cases")
            self.logger.info("Labeling edge case tests...")
            final_labeled = generator.label_test_cases(
                test_cases=final_tests,
                workflow_image_path=str(workflow_image),
                valid_outputs=valid_outputs,
                workflow_analysis=analysis.model_dump(),
                batch_size=batch_size,
                max_workers=max_workers,
                best_of_n=best_of_n,
                max_retries=max_retries,
                backoff_base=backoff_base,
                backoff_cap=backoff_cap,
                log_responses=log_responses,
            )
            final_tests_file.write_text(json.dumps(final_labeled, indent=2), encoding="utf-8")
            self.logger.info("Final test cases saved", extra={"file": str(final_tests_file)})

        print(f"\n🎯 Running final validation on {len(final_labeled)} edge case tests...")
        final_harness = TestHarness(test_cases=final_labeled, valid_outputs=valid_outputs)
        final_score = final_harness.score(code)
        
        # Print formatted final validation score
        status = "✓" if final_score.pass_rate == 1.0 else "⚠️" if final_score.pass_rate >= 0.9 else "❌"
        print(f"{status} Final validation: {final_score.pass_rate*100:.1f}% ({final_score.passed}/{final_score.total} tests passed)")
        if final_score.failures:
            print(f"   Failures: {len(final_score.failures)}")
        
        self.logger.info("Final validation score", extra={
            "pass_rate": final_score.pass_rate,
            "passed": final_score.passed,
            "total": final_score.total
        })
        return final_score.pass_rate
