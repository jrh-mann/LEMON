"""Refinement loop CLI entrypoint.

Core implementation lives in `src.lemon.core.pipeline.RefinementPipeline`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.lemon.config.settings import Settings
from src.lemon.core.pipeline import RefinementPipeline
from src.lemon.utils.logging import configure_logging, get_logger


def main() -> None:
    configure_logging(level="INFO", json_logs=False)
    logger = get_logger(__name__)

    parser = argparse.ArgumentParser(
        description="Refinement loop: Generate deterministic Python code from workflow with test-driven validation"
    )
    parser.add_argument("--workflow-image", type=str, default="workflow.jpeg")
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--num-test-cases", type=int, default=1000, help="Number of test cases to generate (default: 1000)")
    parser.add_argument("--num-final-validation-tests", type=int, default=200, help="Number of edge case tests for final validation (default: 200)")
    
    # Test labeling parameters
    parser.add_argument("--batch-size", type=int, default=20, help="Number of test cases per API call (default: 20)")
    parser.add_argument("--max-workers", type=int, default=5, help="Maximum parallel API calls (default: 5)")
    parser.add_argument("--best-of-n", type=int, default=3, help="Number of labeling passes for majority voting (default: 3)")
    parser.add_argument("--max-retries", type=int, default=3, help="Number of retry attempts on API failure (default: 3)")
    parser.add_argument("--backoff-base", type=float, default=1.0, help="Initial backoff seconds for exponential backoff (default: 1.0)")
    parser.add_argument("--backoff-cap", type=float, default=8.0, help="Maximum backoff seconds (default: 8.0)")
    parser.add_argument("--log-responses", action="store_true", help="Log raw model responses per batch")
    
    args = parser.parse_args()

    # Settings loads from environment variables via pydantic_settings
    pipeline = RefinementPipeline(Settings())  # type: ignore[call-arg]
    result = pipeline.run_with_options(
        workflow_image=Path(args.workflow_image),
        max_iterations=args.max_iterations,
        num_test_cases=args.num_test_cases,
        num_final_validation_tests=args.num_final_validation_tests,
        batch_size=args.batch_size,
        max_workers=args.max_workers,
        best_of_n=args.best_of_n,
        max_retries=args.max_retries,
        backoff_base=args.backoff_base,
        backoff_cap=args.backoff_cap,
        log_responses=args.log_responses,
    )
    # Print final summary
    print("\n" + "=" * 60)
    print("📋 Pipeline Summary")
    print("=" * 60)
    print(f"   Iterations: {result.iterations}")
    print(f"   Best Pass Rate: {result.best_pass_rate*100:.1f}%")
    if result.final_validation_pass_rate is not None:
        print(f"   Final Validation: {result.final_validation_pass_rate*100:.1f}%")
    print(f"   Generated Code: {result.generated_code_path}")
    print("=" * 60 + "\n")

    logger.info(
        "Pipeline finished",
        extra={
            "best_pass_rate": result.best_pass_rate,
            "iterations": result.iterations,
            "generated_code_path": str(result.generated_code_path),
            "final_validation_pass_rate": result.final_validation_pass_rate,
        },
    )


if __name__ == "__main__":
    main()
