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
    args = parser.parse_args()

    pipeline = RefinementPipeline(Settings())
    result = pipeline.run_with_options(
        workflow_image=Path(args.workflow_image), max_iterations=args.max_iterations
    )
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
