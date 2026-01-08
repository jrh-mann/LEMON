"""Normalize test cases: lowercase and strip punctuation from expected_outputs."""

import argparse
import json
import string
from pathlib import Path

from src.lemon.utils.logging import configure_logging, get_logger

configure_logging(level="INFO", json_logs=False)
logger = get_logger(__name__)


def normalize_output(output: str) -> str:
    """Normalize output: lowercase and remove punctuation."""
    if not isinstance(output, str):
        return str(output) if output is not None else ""
    # Remove all punctuation, keep alphanumeric and whitespace
    no_punct = output.translate(str.maketrans("", "", string.punctuation))
    # Lowercase and normalize whitespace
    return " ".join(no_punct.lower().split())


def main():
    parser = argparse.ArgumentParser(
        description="Normalize expected_outputs in test cases (lowercase, strip punctuation)"
    )
    parser.add_argument(
        "-i",
        "--input-file",
        type=str,
        default="labeled_test_cases.json",
        help="Path to labeled test cases JSON file (default: labeled_test_cases.json)",
    )
    parser.add_argument(
        "-o",
        "--output-file",
        type=str,
        default=None,
        help="Path to output file (default: overwrites input file)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without modifying files",
    )

    args = parser.parse_args()

    input_path = Path(args.input_file)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        return 1

    with open(input_path, "r") as f:
        test_cases = json.load(f)

    logger.info(f"Loaded {len(test_cases)} test cases from {input_path}")

    # Normalize expected_outputs
    changed_count = 0
    for tc in test_cases:
        expected = tc.get("expected_output")
        if expected is not None and isinstance(expected, str):
            normalized = normalize_output(expected)
            if normalized != expected:
                if args.dry_run:
                    logger.info(f"Would change: '{expected}' -> '{normalized}'")
                else:
                    tc["expected_output"] = normalized
                changed_count += 1

    if args.dry_run:
        logger.info(f"\nDry run: Would normalize {changed_count} expected_outputs")
        return 0

    # Save normalized test cases
    output_path = Path(args.output_file) if args.output_file else input_path
    with open(output_path, "w") as f:
        json.dump(test_cases, f, indent=2)

    logger.info(f"\nNormalized {changed_count} expected_outputs")
    logger.info(f"Saved to: {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
