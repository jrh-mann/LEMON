"""Script to label unlabeled test cases with expected outputs."""

import argparse
import json
from pathlib import Path

from src.lemon.testing.generator import TestCaseGenerator
from src.lemon.utils.logging import configure_logging, get_logger

configure_logging(level="INFO", json_logs=False)
logger = get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Label test cases with expected outputs using the workflow image"
    )
    parser.add_argument(
        "-i",
        "--input-file",
        type=str,
        default="test_cases.json",
        help="Path to unlabeled test cases JSON file (default: test_cases.json)",
    )
    parser.add_argument(
        "-o",
        "--output-file",
        type=str,
        default="labeled_test_cases.json",
        help="Path to output labeled test cases JSON file (default: labeled_test_cases.json)",
    )
    parser.add_argument(
        "-w",
        "--workflow-image",
        type=str,
        default="workflow.jpeg",
        help="Path to workflow image (default: workflow.jpeg)",
    )
    parser.add_argument(
        "--workflow-outputs",
        type=str,
        default="workflow_outputs.json",
        help="Path to workflow outputs JSON file (default: workflow_outputs.json)",
    )
    parser.add_argument(
        "--workflow-inputs",
        type=str,
        default="workflow_inputs.json",
        help="Path to workflow inputs JSON file (default: workflow_inputs.json)",
    )
    parser.add_argument(
        "-b",
        "--batch-size",
        type=int,
        default=20,
        help="Number of test cases to label per API call (default: 20)",
    )
    parser.add_argument(
        "-m",
        "--model",
        type=str,
        default=None,
        help="Model to use for labeling (default: HAIKU_DEPLOYMENT_NAME or DEPLOYMENT_NAME from env)",
    )
    parser.add_argument(
        "-j",
        "--max-workers",
        type=int,
        default=5,
        help="Maximum parallel API calls (default: 5)",
    )
    parser.add_argument(
        "--log-responses",
        action="store_true",
        help="Log a preview of raw model responses per batch",
    )

    args = parser.parse_args()

    # Load unlabeled test cases
    input_path = Path(args.input_file)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        return 1

    with open(input_path, "r") as f:
        test_cases = json.load(f)

    logger.info(f"Loaded {len(test_cases)} unlabeled test cases from {input_path}")

    # Load valid outputs
    outputs_path = Path(args.workflow_outputs)
    if not outputs_path.exists():
        logger.error(f"Workflow outputs file not found: {outputs_path}")
        return 1

    with open(outputs_path, "r") as f:
        valid_outputs = json.load(f)

    logger.info(f"Loaded {len(valid_outputs)} valid outputs from {outputs_path}")

    # Check workflow image exists
    workflow_image_path = Path(args.workflow_image)
    if not workflow_image_path.exists():
        logger.error(f"Workflow image not found: {workflow_image_path}")
        return 1

    # Initialize generator and label
    generator = TestCaseGenerator(inputs_file=args.workflow_inputs)
    logger.info(f"Labeling {len(test_cases)} test cases (batch size: {args.batch_size})...")

    labeled = generator.label_test_cases(
        test_cases=test_cases,
        workflow_image_path=str(workflow_image_path),
        valid_outputs=valid_outputs,
        model=args.model,
        batch_size=args.batch_size,
        max_workers=args.max_workers,
        log_responses=args.log_responses,
    )

    # Save labeled test cases
    output_path = Path(args.output_file)
    with open(output_path, "w") as f:
        json.dump(labeled, f, indent=2)

    labeled_count = sum(1 for tc in labeled if tc.get("expected_output") is not None)
    logger.info(f"\nLabeled {labeled_count}/{len(labeled)} test cases")
    logger.info(f"Saved to: {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
