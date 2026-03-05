#!/usr/bin/env python
"""Live test: corrupt a valid tree and force the retry harness to trigger.

Takes the diabetes analysis result, deliberately breaks the tree structure,
then feeds it through the validate_and_retry harness with a REAL LLM retry
call to prove the harness can recover.

Usage:
    cd /path/to/LEMON
    python tests/test_harness_retry_live.py

Prerequisites: run test_diabetes_harness_live.py first (needs harness_test_result.json).
"""

from __future__ import annotations

import copy
import json
import logging
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ["LEMON_LOG_PREFIX"] = "harness_retry_test"
os.environ["LEMON_LOG_LEVEL"] = "DEBUG"
os.environ["LEMON_LOG_STDOUT"] = "1"

from src.backend.utils.logging import setup_logging  # noqa: E402

# Reset the logging guard so we get fresh log files for this run
import src.backend.utils.logging as _log_mod  # noqa: E402
_log_mod._CONFIGURED = False

log_path = setup_logging()
print(f"\n=== Logs writing to: {log_path.parent}/harness_retry_test*.log ===\n")

from src.backend.validation.tree_validator import TreeValidator  # noqa: E402
from src.backend.validation.retry_harness import validate_and_retry  # noqa: E402
from src.backend.utils.analysis import normalize_analysis  # noqa: E402
from src.backend.llm import call_llm  # noqa: E402

logger = logging.getLogger("harness_retry_test")


def main() -> None:
    result_path = PROJECT_ROOT / ".lemon" / "harness_test_result.json"
    if not result_path.exists():
        print("ERROR: Run test_diabetes_harness_live.py first to generate the result.")
        sys.exit(1)

    with open(result_path) as f:
        original = json.load(f)

    # --- Validate the original (should pass) ---
    validator = TreeValidator()
    ok, errors = validator.validate(original)
    print(f"Original tree valid: {ok} (errors: {len(errors)})")
    assert ok, f"Original should be valid but got: {errors}"

    # --- Corrupt the tree to trigger specific validation failures ---
    corrupted = copy.deepcopy(original)
    tree_start = corrupted["tree"]["start"]

    # Corruption 1: Give a decision node 0 children (DECISION_CHILDREN_COUNT)
    first_child = tree_start.get("children", [{}])[0]
    if first_child.get("type") == "decision":
        logger.info("Corrupting: removing children from first decision node '%s'", first_child.get("id"))
        first_child["children"] = []
    else:
        # Find any decision node and break it
        _corrupt_first_decision(tree_start)

    # Corruption 2: Give an output node children (OUTPUT_HAS_CHILDREN)
    _add_child_to_first_output(tree_start)

    # Verify corruptions took effect
    ok2, errors2 = validator.validate(corrupted)
    print(f"Corrupted tree valid: {ok2} (errors: {len(errors2)})")
    for e in errors2:
        print(f"  [{e.code}] {e.message}")
    assert not ok2, "Corrupted tree should fail validation"

    # --- Now run the harness with a REAL LLM retry ---
    print(f"\nTriggering validate_and_retry with real LLM call...")
    print("(The LLM will be asked to fix the structural errors)\n")

    # Build the retry function: give the LLM the original JSON + error feedback
    original_json = json.dumps(original, ensure_ascii=False)

    def retry_llm_fn(error_text: str) -> str:
        """Ask the LLM to fix the corrupted tree."""
        prompt = (
            "The following JSON analysis of a workflow has structural errors.\n\n"
            f"ERRORS:\n{error_text}\n\n"
            "Here is the ORIGINAL correct JSON (before corruption). "
            "Return it with the structural errors fixed. Return ONLY valid JSON, no extra text.\n\n"
            f"{original_json}"
        )
        logger.info("Calling LLM for structural retry (%d chars prompt)", len(prompt))
        start = time.perf_counter()
        result = call_llm(
            [{"role": "user", "content": prompt}],
            max_completion_tokens=30000,
            response_format=None,
            caller="harness_retry_test",
            request_tag="structural_retry",
        ).strip()
        elapsed = time.perf_counter() - start
        logger.info("LLM retry response received (%.1fs, %d chars)", elapsed, len(result))
        return result

    def parse_fn(raw: str) -> dict:
        """Parse and normalize the LLM's corrected output."""
        cleaned = raw.strip()
        if cleaned.startswith("```") and cleaned.endswith("```"):
            cleaned = cleaned.strip("`").strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
        parsed = json.loads(cleaned)
        return normalize_analysis(parsed)

    start = time.perf_counter()
    fixed_data, remaining = validate_and_retry(
        data=corrupted,
        validate_fn=validator.validate,
        format_errors_fn=TreeValidator.format_errors,
        retry_llm_fn=retry_llm_fn,
        parse_fn=parse_fn,
        max_retries=2,
        logger=logging.getLogger("backend.subagent"),  # Use the subagent logger
    )
    elapsed = time.perf_counter() - start

    print(f"\n{'=' * 60}")
    print(f"RETRY HARNESS RESULT (took {elapsed:.1f}s)")
    print(f"{'=' * 60}")

    ok3, errors3 = validator.validate(fixed_data)
    print(f"Fixed tree valid: {ok3}")
    print(f"Remaining errors: {len(remaining)}")
    for e in remaining:
        print(f"  [{e.code}] {e.message}")

    if ok3 and not remaining:
        print("\nSUCCESS: Harness recovered from corrupted tree via LLM retry!")
    else:
        print("\nPARTIAL: Harness could not fully recover (errors surfaced as doubts)")

    print(f"\nLog files at: {log_path.parent}/harness_retry_test*.log")
    print(f"Check 'backend.subagent' logger for retry activity.")


def _corrupt_first_decision(node: dict) -> bool:
    """Find first decision node in tree and remove its children."""
    if not isinstance(node, dict):
        return False
    if node.get("type") == "decision" and node.get("children"):
        logger.info("Corrupting: removing children from decision '%s'", node.get("id"))
        node["children"] = []
        return True
    for child in node.get("children", []):
        if _corrupt_first_decision(child):
            return True
    return False


def _add_child_to_first_output(node: dict) -> bool:
    """Find first output node and give it a bogus child."""
    if not isinstance(node, dict):
        return False
    if node.get("type") == "output":
        logger.info("Corrupting: adding child to output '%s'", node.get("id"))
        node["children"] = [{"id": "bogus_child", "type": "action", "label": "Bogus", "children": []}]
        return True
    for child in node.get("children", []):
        if _add_child_to_first_output(child):
            return True
    return False


if __name__ == "__main__":
    main()
