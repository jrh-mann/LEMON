#!/usr/bin/env python
"""Live integration test: run the subagent on the diabetes image and watch the validation harness.

Usage:
    cd /path/to/LEMON
    python tests/test_diabetes_harness_live.py

Logs go to .lemon/logs/harness_test*.log — tail them in another terminal:
    tail -f .lemon/logs/harness_test.log .lemon/logs/harness_test_subagent.log
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Use a dedicated log prefix so we don't clobber the server's logs
os.environ["LEMON_LOG_PREFIX"] = "harness_test"
os.environ["LEMON_LOG_LEVEL"] = "DEBUG"
os.environ["LEMON_LOG_STDOUT"] = "1"  # Also log to console for live watching

from src.backend.utils.logging import setup_logging  # noqa: E402
log_path = setup_logging()
print(f"\n=== Logs writing to: {log_path.parent} ===\n")

import logging  # noqa: E402
from src.backend.agents.subagent import Subagent  # noqa: E402
from src.backend.storage.history import HistoryStore  # noqa: E402

logger = logging.getLogger("harness_test")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

IMAGE_PATH = PROJECT_ROOT / "fixtures" / "images" / "Diabetes Treatment .png"
SESSION_ID = f"harness_test_{int(time.time())}"
HISTORY_DB = PROJECT_ROOT / ".lemon" / "harness_test_history.sqlite"


def main() -> None:
    if not IMAGE_PATH.exists():
        print(f"ERROR: Image not found at {IMAGE_PATH}")
        sys.exit(1)

    logger.info("=== Diabetes Harness Live Test ===")
    logger.info("Image: %s", IMAGE_PATH)
    logger.info("Session: %s", SESSION_ID)

    # Set up real HistoryStore (creates DB if needed)
    history = HistoryStore(HISTORY_DB)
    subagent = Subagent(history)

    # Stream tokens to stdout for real-time progress
    token_count = [0]

    def on_stream(chunk: str) -> None:
        token_count[0] += len(chunk)
        # Print a progress dot every ~500 chars
        if token_count[0] % 500 < len(chunk):
            print(".", end="", flush=True)

    thinking_parts = []

    def on_thinking(chunk: str) -> None:
        thinking_parts.append(chunk)
        # Print thinking progress
        if len(thinking_parts) % 10 == 0:
            print("T", end="", flush=True)

    # --- Run the analysis ---
    print(f"Analyzing diabetes image... (session={SESSION_ID})")
    start = time.perf_counter()

    try:
        result = subagent.analyze(
            image_path=IMAGE_PATH,
            session_id=SESSION_ID,
            feedback=None,
            annotations=None,
            stream=on_stream,
            should_cancel=None,
            on_thinking=on_thinking,
        )
        elapsed = time.perf_counter() - start
        print(f"\n\nAnalysis completed in {elapsed:.1f}s")
    except Exception as exc:
        elapsed = time.perf_counter() - start
        print(f"\n\nAnalysis FAILED after {elapsed:.1f}s: {exc}")
        logger.exception("Analysis failed")
        sys.exit(1)

    # --- Report results ---
    print("\n" + "=" * 60)
    print("RESULT SUMMARY")
    print("=" * 60)

    # Variables
    variables = result.get("variables", [])
    print(f"\nVariables ({len(variables)}):")
    for v in variables:
        print(f"  - {v.get('name')} ({v.get('type')})")

    # Outputs
    outputs = result.get("outputs", [])
    print(f"\nOutputs ({len(outputs)}):")
    for o in outputs:
        print(f"  - {o.get('name')}")

    # Tree structure
    tree = result.get("tree", {})
    start_node = tree.get("start", {})
    node_count = _count_nodes(start_node)
    print(f"\nTree: {node_count} nodes")
    _print_tree(start_node, indent=2)

    # Doubts (including any from validation)
    doubts = result.get("doubts", [])
    print(f"\nDoubts ({len(doubts)}):")
    for d in doubts:
        source = d.get("source", "llm")
        text = d.get("text", str(d))
        marker = " [VALIDATOR]" if source == "tree_validator" else ""
        print(f"  - {text}{marker}")

    # Reasoning summary
    reasoning = result.get("reasoning", "")
    print(f"\nReasoning: {len(reasoning)} chars")

    # Guidance
    guidance = result.get("guidance", [])
    print(f"Guidance items: {len(guidance)}")

    print("\n" + "=" * 60)
    print(f"Log files at: {log_path.parent}/harness_test*.log")
    print("=" * 60)

    # Also dump the full result to a JSON file for inspection
    out_path = PROJECT_ROOT / ".lemon" / "harness_test_result.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"Full result saved to: {out_path}")


def _count_nodes(node: dict, seen: set = None) -> int:
    """Count total nodes in the tree."""
    if not isinstance(node, dict):
        return 0
    if seen is None:
        seen = set()
    nid = node.get("id", id(node))
    if nid in seen:
        return 0
    seen.add(nid)
    count = 1
    for child in node.get("children", []):
        count += _count_nodes(child, seen)
    return count


def _print_tree(node: dict, indent: int = 0) -> None:
    """Pretty-print the tree structure."""
    if not isinstance(node, dict):
        return
    prefix = " " * indent
    ntype = node.get("type", "?")
    label = node.get("label", "?")
    nid = node.get("id", "?")
    edge_label = node.get("edge_label", "")
    edge_str = f" [{edge_label}]" if edge_label else ""
    print(f"{prefix}{ntype}: {label} (id={nid}){edge_str}")
    for child in node.get("children", []):
        _print_tree(child, indent + 2)


if __name__ == "__main__":
    main()
