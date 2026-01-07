"""Run labeled tests against the generated workflow function.

This expects `generated_code.py` to exist (produced by `refine_workflow_code.py`).
"""

from __future__ import annotations

import json
from importlib import import_module

from src.lemon.utils.logging import configure_logging, get_logger

configure_logging(level="INFO", json_logs=False)
logger = get_logger(__name__)

try:
    determine_workflow_outcome = import_module("generated_code").determine_workflow_outcome
except Exception as e:
    raise SystemExit(
        "generated_code.py not found (or does not define determine_workflow_outcome). "
        "Run `uv run python refine_workflow_code.py` first."
    ) from e


def main(test_cases_file: str = "tests.json") -> int:
    with open(test_cases_file, "r", encoding="utf-8") as f:
        test_cases = json.load(f)

    passed = 0
    total = len(test_cases)
    failures = []

    for i, test_case in enumerate(test_cases):
        inputs = {k: v for k, v in test_case.items() if k != "expected_output"}
        expected = test_case.get("expected_output")
        actual = determine_workflow_outcome(inputs)

        actual_norm = str(actual).lower() if actual is not None else None
        expected_norm = str(expected).lower() if expected is not None else None

        if actual_norm == expected_norm:
            passed += 1
        else:
            failures.append(
                {"test_number": i + 1, "inputs": inputs, "expected": expected, "actual": actual}
            )

    logger.info("=" * 80)
    logger.info(f"FAILURES ({len(failures)} total):")
    logger.info("=" * 80)
    logger.info("")

    for failure in failures:
        logger.info(f"Test #{failure['test_number']}:")
        logger.info(f"  Inputs: {failure['inputs']}")
        logger.info(f"  Expected: {failure['expected']}")
        logger.info(f"  Actual:   {failure['actual']}")
        logger.info("")

    logger.info("=" * 80)
    logger.info(f"Passed: {passed}/{total}")
    logger.info(f"Pass rate: {passed/total*100:.2f}%")

    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
