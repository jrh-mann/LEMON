"""Script to label unlabeled test cases with expected outputs."""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from src.lemon.testing.generator import TestCaseGenerator
from src.lemon.utils.logging import configure_logging, get_logger

configure_logging(level="INFO", json_logs=False)
logger = get_logger(__name__)


def _normalize_test_case(tc: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize test case by removing expected_output and sorting keys for comparison."""
    normalized = {k: v for k, v in tc.items() if k != "expected_output"}
    return normalized


def _find_unlabeled_cases(
    all_test_cases: List[Dict[str, Any]], existing_labeled: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Find test cases in all_test_cases that are not labeled in existing_labeled.

    Returns a list of test cases that either:
    - Don't exist in existing_labeled, or
    - Exist but have expected_output as None or missing
    """
    # Create a map of normalized test case -> labeled test case (with expected_output)
    labeled_map: Dict[tuple, Dict[str, Any]] = {}
    for labeled_tc in existing_labeled:
        normalized = _normalize_test_case(labeled_tc)
        # Convert to tuple for hashing (sort keys for consistency)
        key = tuple(sorted(normalized.items()))
        labeled_map[key] = labeled_tc

    # Find unlabeled cases
    unlabeled = []
    for tc in all_test_cases:
        normalized = _normalize_test_case(tc)
        key = tuple(sorted(normalized.items()))

        existing = labeled_map.get(key)
        if existing is None:
            # Not in existing labeled set at all
            unlabeled.append(tc)
        elif existing.get("expected_output") is None:
            # Exists but has no label
            unlabeled.append(tc)

    return unlabeled


def _merge_labeled_results(
    existing_labeled: List[Dict[str, Any]],
    newly_labeled: List[Dict[str, Any]],
    all_test_cases: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge newly labeled results back into existing labeled, preserving order of all_test_cases."""
    # Create a map of normalized test case -> labeled version
    labeled_map: Dict[tuple, Dict[str, Any]] = {}

    # First, add all existing labeled cases
    for labeled_tc in existing_labeled:
        normalized = _normalize_test_case(labeled_tc)
        key = tuple(sorted(normalized.items()))
        labeled_map[key] = labeled_tc

    # Then, update/add with newly labeled cases (these take precedence)
    for labeled_tc in newly_labeled:
        normalized = _normalize_test_case(labeled_tc)
        key = tuple(sorted(normalized.items()))
        labeled_map[key] = labeled_tc

    # Reconstruct in the order of all_test_cases
    merged = []
    for tc in all_test_cases:
        normalized = _normalize_test_case(tc)
        key = tuple(sorted(normalized.items()))
        if key in labeled_map:
            merged.append(labeled_map[key])
        else:
            # Fallback: use original test case (shouldn't happen, but safety)
            merged.append(tc.copy())

    return merged


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
    parser.add_argument(
        "--best-of-n",
        type=int,
        default=3,
        help="Number of independent labeling passes, then take majority vote (default: 3)",
    )

    args = parser.parse_args()

    # Load all test cases (reference)
    input_path = Path(args.input_file)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        return 1

    with open(input_path, "r") as f:
        all_test_cases = json.load(f)

    logger.info(f"Loaded {len(all_test_cases)} test cases from {input_path}")

    # Check if output file already exists (resume mode)
    output_path = Path(args.output_file)
    existing_labeled: List[Dict[str, Any]] = []
    if output_path.exists():
        logger.info(f"Found existing labeled file: {output_path}")
        with open(output_path, "r") as f:
            existing_labeled = json.load(f)

        existing_labeled_count = sum(
            1 for tc in existing_labeled if tc.get("expected_output") is not None
        )
        logger.info(
            f"Existing file has {existing_labeled_count}/{len(existing_labeled)} labeled cases"
        )

        # Find unlabeled cases
        unlabeled_cases = _find_unlabeled_cases(all_test_cases, existing_labeled)
        logger.info(f"Found {len(unlabeled_cases)} unlabeled test cases to process (resume mode)")

        if len(unlabeled_cases) == 0:
            logger.info("All test cases are already labeled! Nothing to do.")
            return 0

        test_cases_to_label = unlabeled_cases
    else:
        logger.info("No existing labeled file found. Starting fresh labeling.")
        test_cases_to_label = all_test_cases

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

    # Initialize generator and label only the unlabeled cases
    generator = TestCaseGenerator(inputs_file=args.workflow_inputs)
    logger.info(
        f"Labeling {len(test_cases_to_label)} test cases (batch size: {args.batch_size})..."
    )

    newly_labeled = generator.label_test_cases(
        test_cases=test_cases_to_label,
        workflow_image_path=str(workflow_image_path),
        valid_outputs=valid_outputs,
        model=args.model,
        batch_size=args.batch_size,
        max_workers=args.max_workers,
        log_responses=args.log_responses,
        best_of_n=args.best_of_n,
    )

    # Merge results
    if output_path.exists():
        logger.info("Merging newly labeled cases with existing labeled cases...")
        merged_labeled = _merge_labeled_results(existing_labeled, newly_labeled, all_test_cases)
        final_labeled = merged_labeled
    else:
        final_labeled = newly_labeled

    # Save merged results
    with open(output_path, "w") as f:
        json.dump(final_labeled, f, indent=2)

    final_labeled_count = sum(1 for tc in final_labeled if tc.get("expected_output") is not None)
    newly_labeled_count = sum(1 for tc in newly_labeled if tc.get("expected_output") is not None)

    logger.info(f"\n{'='*60}")
    logger.info(f"Labeling complete!")
    logger.info(f"  - Newly labeled in this run: {newly_labeled_count}/{len(newly_labeled)}")
    logger.info(f"  - Total labeled: {final_labeled_count}/{len(final_labeled)}")
    logger.info(f"  - Saved to: {output_path}")
    logger.info(f"{'='*60}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
