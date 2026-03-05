#!/usr/bin/env python
"""End-to-end conversation test: analyze diabetes image, clarify doubts, regenerate.

Simulates a doctor using the frontend:
  Turn 1: Upload image → get analysis + doubts
  Turn 2: Answer all doubts with ground-truth-informed clarifications
  Turn 3: Request regenerated JSON with corrections applied
  Compare: Check regenerated tree against ground truth

Usage:
    cd /path/to/LEMON
    python tests/test_diabetes_conversation.py

Logs:  .lemon/logs/convo_test*.log
"""

from __future__ import annotations

import copy
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ["LEMON_LOG_PREFIX"] = "convo_test"
os.environ["LEMON_LOG_LEVEL"] = "DEBUG"
os.environ["LEMON_LOG_STDOUT"] = "1"

# Reset logging guard for a fresh log file
import src.backend.utils.logging as _log_mod
_log_mod._CONFIGURED = False
from src.backend.utils.logging import setup_logging  # noqa: E402

log_path = setup_logging()
print(f"\n=== Logs: {log_path.parent}/convo_test*.log ===\n")

import logging  # noqa: E402
from src.backend.agents.subagent import Subagent  # noqa: E402
from src.backend.storage.history import HistoryStore  # noqa: E402
from evals.ground_truth.diabetes_ground_truth import (  # noqa: E402
    INPUT_SCHEMA,
    POSSIBLE_OUTPUTS,
    TEST_CASES,
    determine_workflow_outcome,
)

logger = logging.getLogger("convo_test")

IMAGE_PATH = PROJECT_ROOT / "fixtures" / "images" / "Diabetes Treatment .png"
SESSION_ID = f"convo_test_{int(time.time())}"
HISTORY_DB = PROJECT_ROOT / ".lemon" / "convo_test_history.sqlite"

# Ground-truth-informed answers to the three doubts the LLM typically raises.
# These are the "doctor's" decisions based on our handmade ground truth.
DOUBT_ANSWERS = {
    "dual_therapy": (
        "The 'Gliptin OR Pioglitazone OR Gliclazide' section should be modeled as a "
        "single action node. The choice between agents is an input variable "
        "(dual_agent_choice with values: gliptin, pioglitazone, gliclazide), not "
        "separate decision branches. The node label should be something like "
        "'Start Dual Therapy' and the specific agent is selected by the input."
    ),
    "bmi_check": (
        "Yes, there SHOULD be an explicit decision node checking BMI >= 23 before "
        "GLP initiation. The purple box note 'Minimum BMI for GLP Initiation is 23' "
        "is a hard gate: if BMI < 23, the patient stays on triple therapy "
        "(Metformin + Gliptin/Pioglitazone/Gliclazide, consider SGLT2i) and does "
        "NOT proceed to GLP-1 agonists (Ozempic/Mounjaro). Add a decision node "
        "with condition bmi >= 23 before the 'Add GLP' action."
    ),
    "scheduling": (
        "The 'Scheduling Follow-up' note is administrative guidance, NOT a clinical "
        "decision node. It should NOT be represented in the workflow tree. It applies "
        "to all dose-change scenarios and is handled outside the decision algorithm."
    ),
}


def main() -> None:
    if not IMAGE_PATH.exists():
        print(f"ERROR: Image not found at {IMAGE_PATH}")
        sys.exit(1)

    history = HistoryStore(HISTORY_DB)
    subagent = Subagent(history)

    # ------------------------------------------------------------------
    # TURN 1: Initial image analysis
    # ------------------------------------------------------------------
    print("=" * 60)
    print("TURN 1: Analyzing diabetes image...")
    print("=" * 60)

    t0 = time.perf_counter()
    result1 = subagent.analyze(
        image_path=IMAGE_PATH,
        session_id=SESSION_ID,
        feedback=None,
        annotations=None,
        stream=lambda _: None,
        should_cancel=None,
        on_thinking=lambda _: None,
    )
    t1 = time.perf_counter()
    print(f"  Done in {t1 - t0:.1f}s")

    _print_analysis_summary("Turn 1", result1)

    # Save turn 1 result
    _save_result("turn1", result1)

    doubts = result1.get("doubts", [])
    if not doubts:
        print("\n  No doubts raised — the LLM is confident. Skipping clarification.")
    else:
        # ------------------------------------------------------------------
        # TURN 2: Clarify all doubts in a single follow-up
        # ------------------------------------------------------------------
        print("\n" + "=" * 60)
        print("TURN 2: Clarifying doubts...")
        print("=" * 60)

        feedback = _build_feedback(doubts)
        print(f"  Sending {len(feedback)} chars of feedback\n")
        print("  --- Feedback preview ---")
        for line in feedback.split("\n"):
            if line.strip():
                print(f"  {line[:100]}{'...' if len(line) > 100 else ''}")
        print("  ---\n")

        t2 = time.perf_counter()
        result2 = subagent.analyze(
            image_path=IMAGE_PATH,
            session_id=SESSION_ID,
            feedback=feedback,
            annotations=None,
            stream=lambda _: None,
            should_cancel=None,
            on_thinking=lambda _: None,
        )
        t3 = time.perf_counter()
        print(f"  Done in {t3 - t2:.1f}s")

        # This is a follow-up with "regenerate json" trigger so we get JSON back
        if "message" in result2 and "tree" not in result2:
            print(f"\n  Got conversational reply: {result2['message'][:200]}...")
            print("  (No JSON regeneration triggered, will do turn 3)")

            # ------------------------------------------------------------------
            # TURN 3: Explicitly request JSON regeneration
            # ------------------------------------------------------------------
            print("\n" + "=" * 60)
            print("TURN 3: Requesting JSON regeneration...")
            print("=" * 60)

            regen_feedback = (
                "Based on my clarifications above, please regenerate the full json "
                "with these corrections applied: (1) add a BMI >= 23 decision node "
                "before GLP initiation, (2) model dual therapy as a single action "
                "node with a dual_agent_choice input variable, (3) do NOT include "
                "the scheduling follow-up as a node."
            )
            t4 = time.perf_counter()
            result3 = subagent.analyze(
                image_path=IMAGE_PATH,
                session_id=SESSION_ID,
                feedback=regen_feedback,
                annotations=None,
                stream=lambda _: None,
                should_cancel=None,
                on_thinking=lambda _: None,
            )
            t5 = time.perf_counter()
            print(f"  Done in {t5 - t4:.1f}s")

            if "tree" in result3:
                _print_analysis_summary("Turn 3 (regenerated)", result3)
                _save_result("turn3", result3)
                _compare_to_ground_truth(result3)
            else:
                print(f"  Got message instead of JSON: {result3.get('message', '')[:200]}")
        else:
            # Turn 2 returned full JSON (the feedback contained "regenerate json")
            _print_analysis_summary("Turn 2 (regenerated)", result2)
            _save_result("turn2", result2)
            _compare_to_ground_truth(result2)

    print(f"\nLogs: {log_path.parent}/convo_test*.log")
    print(f"Results: .lemon/convo_test_turn*.json")


# ------------------------------------------------------------------
# Feedback construction
# ------------------------------------------------------------------

def _build_feedback(doubts: List[Dict[str, Any]]) -> str:
    """Build a single feedback message that answers all doubts and requests regeneration."""
    lines = [
        "Thank you for the analysis. Here are my clarifications on your questions:\n"
    ]

    for i, doubt in enumerate(doubts, 1):
        q = doubt.get("question", doubt.get("text", str(doubt)))
        # Match doubt to our prepared answers based on keywords
        answer = _match_doubt_answer(q)
        lines.append(f"Q{i}: {q}")
        lines.append(f"A{i}: {answer}\n")

    lines.append(
        "Please regenerate the full json incorporating these corrections. "
        "Key changes: add a BMI >= 23 decision gate before GLP initiation, "
        "model dual therapy choice as an input variable (not separate branches), "
        "and exclude scheduling/follow-up from the tree."
    )

    return "\n".join(lines)


def _match_doubt_answer(question: str) -> str:
    """Match a doubt question to our prepared ground-truth answer."""
    q_lower = question.lower()
    if any(kw in q_lower for kw in ["gliptin", "pioglitazone", "gliclazide", "dual therapy", "three separate"]):
        return DOUBT_ANSWERS["dual_therapy"]
    if any(kw in q_lower for kw in ["bmi", "23", "glp initiation"]):
        return DOUBT_ANSWERS["bmi_check"]
    if any(kw in q_lower for kw in ["scheduling", "follow-up", "follow up", "booking", "14 weeks"]):
        return DOUBT_ANSWERS["scheduling"]
    # Generic fallback for unexpected doubts
    return (
        "This is administrative or contextual information that should not be "
        "modeled as a decision node. Keep the tree focused on clinical decisions."
    )


# ------------------------------------------------------------------
# Comparison with ground truth
# ------------------------------------------------------------------

def _compare_to_ground_truth(result: Dict[str, Any]) -> None:
    """Compare the regenerated analysis against our ground truth."""
    print("\n" + "=" * 60)
    print("COMPARISON WITH GROUND TRUTH")
    print("=" * 60)

    variables = result.get("variables", [])
    var_names = {v.get("name") for v in variables if isinstance(v, dict)}
    gt_var_names = {v["name"] for v in INPUT_SCHEMA}

    print(f"\n--- Variables ---")
    print(f"  LLM: {len(variables)} variables")
    print(f"  Ground truth: {len(INPUT_SCHEMA)} variables")
    matched = var_names & gt_var_names
    missing = gt_var_names - var_names
    extra = var_names - gt_var_names
    print(f"  Matched: {len(matched)}")
    if matched:
        for m in sorted(matched):
            print(f"    + {m}")
    if missing:
        print(f"  Missing from LLM ({len(missing)}):")
        for m in sorted(missing):
            print(f"    - {m}")
    if extra:
        print(f"  Extra in LLM ({len(extra)}):")
        for e in sorted(extra):
            print(f"    ~ {e}")

    outputs = result.get("outputs", [])
    out_names = {o.get("name", o.get("label", "")) for o in outputs if isinstance(o, dict)}
    gt_out_names = set(POSSIBLE_OUTPUTS)

    print(f"\n--- Outputs ---")
    print(f"  LLM: {len(outputs)} outputs")
    print(f"  Ground truth: {len(POSSIBLE_OUTPUTS)} possible outputs")
    out_matched = out_names & gt_out_names
    out_missing = gt_out_names - out_names
    out_extra = out_names - gt_out_names
    print(f"  Matched: {len(out_matched)}")
    if out_missing:
        print(f"  Missing from LLM ({len(out_missing)}):")
        for m in sorted(out_missing):
            print(f"    - {m}")
    if out_extra:
        print(f"  Extra in LLM ({len(out_extra)}):")
        for e in sorted(out_extra):
            print(f"    ~ {e}")

    # Check key structural features
    tree = result.get("tree", {})
    start = tree.get("start", {})

    print(f"\n--- Key Structural Checks ---")

    # Check 1: BMI gate exists before GLP
    bmi_node = _find_node_by_keyword(start, "bmi")
    print(f"  BMI >= 23 gate present: {'YES' if bmi_node else 'NO'}")
    if bmi_node:
        print(f"    Found: {bmi_node.get('label')} (id={bmi_node.get('id')})")

    # Check 2: Dual therapy is a single action (not a 3-way branch)
    dual_node = _find_node_by_keyword(start, "dual")
    gliptin_decision = _find_node_by_keyword(start, "gliptin or")
    print(f"  Dual therapy as single node: {'YES' if dual_node and not gliptin_decision else 'UNCLEAR'}")

    # Check 3: No scheduling node
    sched_node = _find_node_by_keyword(start, "scheduling")
    follow_node = _find_node_by_keyword(start, "follow-up")
    print(f"  Scheduling node absent: {'YES' if not sched_node and not follow_node else 'NO — still present'}")

    # Check 4: Prognostic value split (Ozempic vs Mounjaro)
    ozempic_node = _find_node_by_keyword(start, "ozempic")
    mounjaro_node = _find_node_by_keyword(start, "mounjaro")
    prog_node = _find_node_by_keyword(start, "prognostic")
    print(f"  Prognostic value split: {'YES' if prog_node else 'NO'}")
    print(f"  Ozempic node: {'YES' if ozempic_node else 'NO'}")
    print(f"  Mounjaro node: {'YES' if mounjaro_node else 'NO'}")

    # Check 5: CVD split
    cvd_node = _find_node_by_keyword(start, "cvd")
    print(f"  CVD risk split: {'YES' if cvd_node else 'NO'}")

    # Check 6: Total node count
    node_count = _count_nodes(start)
    print(f"  Total nodes: {node_count}")

    # Count by type
    type_counts: Dict[str, int] = {}
    _count_by_type(start, type_counts)
    print(f"  By type: {dict(sorted(type_counts.items()))}")

    # Validator doubts
    doubts = result.get("doubts", [])
    validator_doubts = [d for d in doubts if isinstance(d, dict) and d.get("source") == "tree_validator"]
    print(f"\n  Validator doubts (structural issues): {len(validator_doubts)}")
    for d in validator_doubts:
        print(f"    ! {d.get('text', d)}")


# ------------------------------------------------------------------
# Tree search helpers
# ------------------------------------------------------------------

def _find_node_by_keyword(node: dict, keyword: str) -> dict | None:
    """DFS for first node whose label contains keyword (case-insensitive)."""
    if not isinstance(node, dict):
        return None
    label = (node.get("label") or "").lower()
    cond = node.get("condition", {})
    input_id = (cond.get("input_id") or "") if isinstance(cond, dict) else ""
    if keyword.lower() in label or keyword.lower() in input_id.lower():
        return node
    for child in node.get("children", []):
        found = _find_node_by_keyword(child, keyword)
        if found:
            return found
    return None


def _count_nodes(node: dict, seen: set = None) -> int:
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


def _count_by_type(node: dict, counts: dict) -> None:
    if not isinstance(node, dict):
        return
    ntype = node.get("type", "unknown")
    counts[ntype] = counts.get(ntype, 0) + 1
    for child in node.get("children", []):
        _count_by_type(child, counts)


# ------------------------------------------------------------------
# Output helpers
# ------------------------------------------------------------------

def _print_analysis_summary(label: str, result: Dict[str, Any]) -> None:
    variables = result.get("variables", [])
    outputs = result.get("outputs", [])
    tree = result.get("tree", {})
    start = tree.get("start", {})
    doubts = result.get("doubts", [])
    node_count = _count_nodes(start)

    print(f"\n  --- {label} ---")
    print(f"  Variables: {len(variables)}")
    print(f"  Outputs: {len(outputs)}")
    print(f"  Tree nodes: {node_count}")
    print(f"  Doubts: {len(doubts)}")

    for i, d in enumerate(doubts, 1):
        q = d.get("question", d.get("text", str(d)))
        source = d.get("source", "llm")
        tag = " [VALIDATOR]" if source == "tree_validator" else ""
        print(f"    {i}. {q[:120]}{'...' if len(str(q)) > 120 else ''}{tag}")

    _print_tree(start, indent=4)


def _print_tree(node: dict, indent: int = 0) -> None:
    if not isinstance(node, dict):
        return
    prefix = " " * indent
    ntype = node.get("type", "?")
    label = node.get("label", "?")
    nid = node.get("id", "?")
    edge = node.get("edge_label", "")
    edge_str = f" [{edge}]" if edge else ""
    print(f"{prefix}{ntype}: {label} (id={nid}){edge_str}")
    for child in node.get("children", []):
        _print_tree(child, indent + 2)


def _save_result(turn: str, result: Dict[str, Any]) -> None:
    out_path = PROJECT_ROOT / ".lemon" / f"convo_test_{turn}.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"  Saved to: {out_path}")


if __name__ == "__main__":
    main()
