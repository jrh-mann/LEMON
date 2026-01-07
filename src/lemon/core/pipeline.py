"""Pipeline orchestration for LEMON."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..analysis.agent import WorkflowAnalyzer
from ..config.settings import Settings
from ..core.workflow import StandardizedInput, WorkflowAnalysis
from ..generation.generator import CodeGenerator, GenerationContext
from ..generation.validator import has_entrypoint_function
from ..testing.generator import TestCaseGenerator
from ..testing.harness import TestHarness, TestResults
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
        self.analyzer = WorkflowAnalyzer(max_tokens=16000)
        self.test_generator = TestCaseGenerator()
        self.code_generator = CodeGenerator()

    def _emit(self, stage: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        if self._progress_callback:
            self._progress_callback(stage, message, data or {})

    def run(self, workflow_image: Path) -> PipelineResult:
        """Run the pipeline until convergence (100% pass rate)."""
        return self.run_with_options(workflow_image=workflow_image, max_iterations=None)

    def run_with_options(
        self, *, workflow_image: Path, max_iterations: Optional[int]
    ) -> PipelineResult:
        """Run the pipeline with optional iteration cap."""
        base_dir = Path.cwd()

        self._emit("setup", "Starting pipeline...", {"workflow_image": str(workflow_image)})
        valid_outputs, analysis = self._load_or_analyze(
            base_dir=base_dir, workflow_image=workflow_image
        )
        labeled_tests = self._load_or_generate_tests(
            base_dir=base_dir, workflow_image=workflow_image, valid_outputs=valid_outputs, analysis=analysis
        )

        harness = TestHarness(test_cases=labeled_tests, valid_outputs=valid_outputs)

        failures: Optional[List[Dict[str, Any]]] = None
        best = 0.0
        code: str = ""
        iteration = 0

        self.logger.info("Starting refinement loop")
        while True:
            iteration += 1
            if max_iterations is not None and iteration > max_iterations:
                self.logger.warning(
                    "Reached max iterations; stopping", extra={"max_iterations": max_iterations}
                )
                self._emit(
                    "refinement",
                    "⚠️ Reached max iterations; stopping",
                    {"max_iterations": max_iterations},
                )
                break

            self.logger.info(f"Starting iteration {iteration}", extra={"iteration": iteration, "best_pass_rate": best})
            self._emit(
                "refinement",
                f"🔄 Iteration {iteration} (best: {best*100:.1f}%)",
                {"iteration": iteration, "best_pass_rate": best},
            )
            
            self.logger.info("Generating code...")
            self._emit("code_generation", "💻 Generating Python code...")
            ctx = GenerationContext(failures=failures, test_cases_file=base_dir / "tests.json")
            code = self.code_generator.generate(
                workflow_image_path=workflow_image,
                workflow_data=analysis,
                valid_outputs=valid_outputs,
                context=ctx,
            )
            self.logger.info("Code generated", extra={"length": len(code)})

            if not has_entrypoint_function(code):
                self.logger.warning(
                    "Generated code missing entrypoint; retrying", extra={"iteration": iteration}
                )
                self._emit(
                    "code_generation",
                    "❌ Generated invalid code structure; retrying",
                    {"iteration": iteration},
                )
                continue

            generated_code_path = base_dir / "generated_code.py"
            generated_code_path.write_text(code, encoding="utf-8")
            self.logger.info("Code saved", extra={"path": str(generated_code_path)})
            self._emit("code_generation", "✓ Code generated and saved", {"code": code})

            self.logger.info("Testing code against labeled test cases...")
            self._emit("testing", "🧪 Running tests...")
            results: TestResults = harness.score(code)
            self.logger.info("Testing complete", extra={"passed": results.passed, "total": results.total})
            pass_rate = results.pass_rate
            best = max(best, pass_rate)

            self.logger.info(
                "Iteration score",
                extra={
                    "iteration": iteration,
                    "pass_rate": pass_rate,
                    "passed": results.passed,
                    "total": results.total,
                    "failures": len(results.failures),
                },
            )
            
            status_emoji = "✓" if pass_rate == 1.0 else "⚠️" if pass_rate >= 0.9 else "❌"
            self._emit(
                "testing",
                f"{status_emoji} Score: {pass_rate*100:.1f}% ({results.passed}/{results.total})",
                {
                    "score": pass_rate,
                    "passed": results.passed,
                    "total": results.total,
                    "failures": [f.__dict__ for f in results.failures[:5]],
                },
            )

            if pass_rate == 1.0:
                self.logger.info("🎉 Perfect score achieved!")
                self._emit("refinement", "✓ 100% pass rate achieved!")
                break

            self.logger.info(f"Collecting {len(results.failures)} failures for next iteration")
            failures = [{"error": f.error, "test_case": f.test_case} for f in results.failures]

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
            generated_code_path=Path.cwd() / "generated_code.py",
            pass_rate=(harness.score(code).pass_rate if code else 0.0),
            iterations=iteration,
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
        analysis = self.analyzer.analyze(workflow_image)
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
        self, *, base_dir: Path, workflow_image: Path, valid_outputs: List[str], analysis: WorkflowAnalysis
    ) -> List[Dict[str, Any]]:
        tests_file = base_dir / "tests.json"
        if tests_file.exists():
            self.logger.info("Loading cached test cases")
            self._emit("test_generation", "✓ Found existing test cases; loading cached file")
            cached = json.loads(tests_file.read_text(encoding="utf-8"))
            labeled_count = len([t for t in cached if t.get('expected_output') is not None])
            self.logger.info("Test cases loaded", extra={"total": len(cached), "labeled": labeled_count})
            return cached if isinstance(cached, list) else []

        self.logger.info("Generating test cases...", extra={"count": 1000, "strategy": "comprehensive"})
        self._emit("test_generation", "🎲 Generating 1000 initial test cases...")
        generator = TestCaseGenerator(str(base_dir / "workflow_inputs.json"))
        test_cases = generator.generate_test_cases(1000, "comprehensive")
        self.logger.info("Test cases generated", extra={"count": len(test_cases)})
        
        self.logger.info("Labeling test cases with workflow analysis context...")
        self._emit("test_generation", "🏷️ Labeling test cases (this may take a few minutes)...")
        labeled = generator.label_test_cases(
            test_cases=test_cases,
            workflow_image_path=str(workflow_image),
            valid_outputs=valid_outputs,
            workflow_analysis=analysis.model_dump(),
        )
        self.logger.info("Test cases labeled", extra={"count": len(labeled)})
        
        tests_file.write_text(json.dumps(labeled, indent=2), encoding="utf-8")
        self.logger.info("Test cases saved", extra={"file": str(tests_file)})
        self._emit("test_generation", f"✓ {len(labeled)} test cases generated and labeled", {"count": len(labeled)})
        return labeled

    def _final_validation(
        self, *, base_dir: Path, workflow_image: Path, valid_outputs: List[str], code: str, analysis: WorkflowAnalysis
    ) -> float:
        final_tests_file = base_dir / "final_tests.json"
        if final_tests_file.exists():
            self.logger.info("Loading cached final test cases")
            final_labeled = json.loads(final_tests_file.read_text(encoding="utf-8"))
        else:
            self.logger.info("Generating 200 edge case tests...")
            generator = TestCaseGenerator(str(base_dir / "workflow_inputs.json"))
            final_tests = generator.generate_test_cases(200, "edge_cases")
            self.logger.info("Labeling edge case tests...")
            final_labeled = generator.label_test_cases(
                test_cases=final_tests,
                workflow_image_path=str(workflow_image),
                valid_outputs=valid_outputs,
                workflow_analysis=analysis.model_dump(),
            )
            final_tests_file.write_text(json.dumps(final_labeled, indent=2), encoding="utf-8")
            self.logger.info("Final test cases saved", extra={"file": str(final_tests_file)})

        self.logger.info("Running final validation tests...", extra={"count": len(final_labeled)})
        final_harness = TestHarness(test_cases=final_labeled, valid_outputs=valid_outputs)
        final_score = final_harness.score(code)
        self.logger.info("Final validation score", extra={
            "pass_rate": final_score.pass_rate,
            "passed": final_score.passed,
            "total": final_score.total
        })
        return final_score.pass_rate
