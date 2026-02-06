#!/usr/bin/env python3
"""
Evaluation runner for workflow image extraction accuracy.

Extracts a workflow from a test image using the Subagent, then compares
the output against a hand-crafted golden solution.  Prints a per-dimension
accuracy report.

Usage:
    python -m eval.run_eval                        # defaults to workflow_test.jpeg
    python -m eval.run_eval --image workflow.jpeg   # specify image
    python -m eval.run_eval --runs 3               # multiple extraction runs
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
import uuid
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Project imports — kept to the absolute minimum needed to run extraction
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from backend.agents.subagent import Subagent  # noqa: E402
from backend.storage.history import HistoryStore  # noqa: E402
from backend.utils.analysis import normalize_analysis  # noqa: E402

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
IMAGE_DIR = PROJECT_ROOT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger("eval")


# ═══════════════════════════════════════════════════════════════════════════
#  1. Extraction wrapper
# ═══════════════════════════════════════════════════════════════════════════

def run_extraction(image_path: Path) -> Dict[str, Any]:
    """Run the subagent extraction pipeline on an image and return the
    normalized analysis dict (with 'variables' key, not 'inputs')."""
    # Use a throwaway SQLite DB so eval runs don't pollute real history
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "eval_history.sqlite"
        history = HistoryStore(db_path)
        session_id = uuid.uuid4().hex
        history.create_session(session_id, image_path.name)
        subagent = Subagent(history)
        result = subagent.analyze(
            image_path=image_path,
            session_id=session_id,
        )
    return result


# ═══════════════════════════════════════════════════════════════════════════
#  2. Tree helpers
# ═══════════════════════════════════════════════════════════════════════════

def flatten_tree(node: Dict[str, Any], parent_id: Optional[str] = None,
                 edge_label: Optional[str] = None) -> List[Dict[str, Any]]:
    """Flatten a nested tree into a list of node dicts, each annotated with
    parent_id and the edge_label from parent → this node."""
    flat: List[Dict[str, Any]] = []
    entry = {
        "id": node.get("id", ""),
        "type": node.get("type", ""),
        "label": node.get("label", ""),
        "parent_id": parent_id,
        "edge_label": edge_label or node.get("edge_label", ""),
        "input_ids": node.get("input_ids", []),
        "condition": node.get("condition"),
        "children_count": len(node.get("children", [])),
    }
    flat.append(entry)
    for child in node.get("children", []):
        flat.extend(flatten_tree(child, parent_id=node["id"],
                                 edge_label=child.get("edge_label", "")))
    return flat


# ═══════════════════════════════════════════════════════════════════════════
#  3. Matching helpers
# ═══════════════════════════════════════════════════════════════════════════

def _normalise_label(text: str) -> str:
    """Lower-case, strip punctuation, collapse whitespace — for fuzzy matching."""
    import re
    text = text.lower().strip()
    text = re.sub(r"[''\"\"\"?]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def label_similarity(a: str, b: str) -> float:
    """Return 0-1 similarity score between two labels.

    Uses SequenceMatcher but also boosts the score when one normalised
    label is a substring of the other (handles 'LDL' vs 'LDL Level')."""
    na, nb = _normalise_label(a), _normalise_label(b)
    seq_score = SequenceMatcher(None, na, nb).ratio()
    # Substring containment boost: if the shorter string (>2 chars) is
    # fully contained in the longer one, ensure score is at least 0.7.
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(shorter) > 2 and shorter in longer:
        seq_score = max(seq_score, 0.7)
    return seq_score


def match_nodes(
    golden_nodes: List[Dict[str, Any]],
    extracted_nodes: List[Dict[str, Any]],
    threshold: float = 0.55,
) -> List[Tuple[Dict[str, Any], Optional[Dict[str, Any]], float]]:
    """Greedily match golden nodes to extracted nodes by label similarity.

    Returns list of (golden_node, matched_extracted_node_or_None, score).
    Each extracted node is used at most once."""
    # Build similarity matrix
    pairs: List[Tuple[float, int, int]] = []
    for gi, g in enumerate(golden_nodes):
        for ei, e in enumerate(extracted_nodes):
            sim = label_similarity(g["label"], e["label"])
            if sim >= threshold:
                pairs.append((sim, gi, ei))
    # Sort descending by similarity — greedy best-first
    pairs.sort(key=lambda t: -t[0])
    used_g: set[int] = set()
    used_e: set[int] = set()
    matches: Dict[int, Tuple[int, float]] = {}
    for sim, gi, ei in pairs:
        if gi in used_g or ei in used_e:
            continue
        matches[gi] = (ei, sim)
        used_g.add(gi)
        used_e.add(ei)

    result: List[Tuple[Dict[str, Any], Optional[Dict[str, Any]], float]] = []
    for gi, g in enumerate(golden_nodes):
        if gi in matches:
            ei, sim = matches[gi]
            result.append((g, extracted_nodes[ei], sim))
        else:
            result.append((g, None, 0.0))
    return result


# ═══════════════════════════════════════════════════════════════════════════
#  4. Scoring dimensions
# ═══════════════════════════════════════════════════════════════════════════

def score_variables(golden: Dict, extracted: Dict) -> Dict[str, Any]:
    """Score how well the extracted variables match the golden variables.

    Matches by name similarity; checks type correctness for matched pairs."""
    g_vars = golden.get("variables") or golden.get("inputs", [])
    e_vars = extracted.get("variables") or extracted.get("inputs", [])

    matched = 0
    type_correct = 0
    details: List[Dict[str, Any]] = []

    used: set[int] = set()
    for gv in g_vars:
        best_score = 0.0
        best_idx = -1
        for ei, ev in enumerate(e_vars):
            if ei in used:
                continue
            sim = label_similarity(gv["name"], ev["name"])
            if sim > best_score:
                best_score = sim
                best_idx = ei
        if best_score >= 0.55 and best_idx >= 0:
            matched += 1
            used.add(best_idx)
            ev = e_vars[best_idx]
            tc = gv["type"] == ev["type"]
            if tc:
                type_correct += 1
            details.append({
                "golden": gv["name"],
                "extracted": ev["name"],
                "label_sim": round(best_score, 3),
                "type_match": tc,
                "golden_type": gv["type"],
                "extracted_type": ev["type"],
            })
        else:
            details.append({
                "golden": gv["name"],
                "extracted": None,
                "label_sim": 0.0,
                "type_match": False,
            })

    total_golden = len(g_vars)
    total_extracted = len(e_vars)
    precision = matched / total_extracted if total_extracted else 0.0
    recall = matched / total_golden if total_golden else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "type_accuracy": round(type_correct / matched, 3) if matched else 0.0,
        "golden_count": total_golden,
        "extracted_count": total_extracted,
        "matched": matched,
        "details": details,
    }


def score_tree_nodes(golden: Dict, extracted: Dict) -> Dict[str, Any]:
    """Score node identification — were the right nodes found with the right types?"""
    g_tree = golden.get("tree", {}).get("start")
    e_tree = extracted.get("tree", {}).get("start")
    if not g_tree or not e_tree:
        return {"error": "Missing tree in golden or extracted"}

    g_flat = flatten_tree(g_tree)
    e_flat = flatten_tree(e_tree)
    node_matches = match_nodes(g_flat, e_flat)

    matched = sum(1 for _, e, _ in node_matches if e is not None)
    type_correct = 0
    edge_label_correct = 0
    matched_with_edge = 0
    details: List[Dict[str, Any]] = []

    for g, e, sim in node_matches:
        if e is None:
            details.append({
                "golden_label": g["label"],
                "golden_type": g["type"],
                "matched": False,
            })
            continue
        tc = g["type"] == e["type"]
        # Also accept action<->process mapping
        if not tc and {g["type"], e["type"]} <= {"action", "process"}:
            tc = True
        if tc:
            type_correct += 1
        # Edge label scoring (only for nodes that have edge labels in golden)
        el_correct = False
        if g["edge_label"]:
            matched_with_edge += 1
            el_correct = label_similarity(g["edge_label"], e.get("edge_label", "")) > 0.6
            if el_correct:
                edge_label_correct += 1
        details.append({
            "golden_label": g["label"],
            "extracted_label": e["label"],
            "label_sim": round(sim, 3),
            "type_match": tc,
            "edge_label_match": el_correct,
            "golden_type": g["type"],
            "extracted_type": e["type"],
        })

    total_golden = len(g_flat)
    total_extracted = len(e_flat)
    precision = matched / total_extracted if total_extracted else 0.0
    recall = matched / total_golden if total_golden else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "type_accuracy": round(type_correct / matched, 3) if matched else 0.0,
        "edge_label_accuracy": round(edge_label_correct / matched_with_edge, 3) if matched_with_edge else 0.0,
        "golden_count": total_golden,
        "extracted_count": total_extracted,
        "matched": matched,
        "details": details,
    }


def score_topology(golden: Dict, extracted: Dict) -> Dict[str, Any]:
    """Score whether parent-child relationships are correct for matched nodes.

    For each matched golden node, check if its parent in golden was also
    matched and whether the extracted node has the same parent."""
    g_tree = golden.get("tree", {}).get("start")
    e_tree = extracted.get("tree", {}).get("start")
    if not g_tree or not e_tree:
        return {"error": "Missing tree"}

    g_flat = flatten_tree(g_tree)
    e_flat = flatten_tree(e_tree)
    node_matches = match_nodes(g_flat, e_flat)

    # Build golden_id → extracted_id mapping for matched nodes
    g_to_e: Dict[str, str] = {}
    for g, e, _ in node_matches:
        if e is not None:
            g_to_e[g["id"]] = e["id"]

    correct = 0
    total = 0
    details: List[Dict[str, Any]] = []

    for g, e, _ in node_matches:
        if e is None:
            continue
        if g["parent_id"] is None:
            # Root node — no parent to check
            continue
        total += 1
        # The golden parent should also be matched, and the extracted node's
        # parent should be the match of the golden parent.
        expected_e_parent = g_to_e.get(g["parent_id"])
        actual_e_parent = e.get("parent_id")
        is_correct = (expected_e_parent is not None and
                      expected_e_parent == actual_e_parent)
        if is_correct:
            correct += 1
        details.append({
            "golden_node": g["label"],
            "golden_parent": g["parent_id"],
            "expected_extracted_parent": expected_e_parent,
            "actual_extracted_parent": actual_e_parent,
            "correct": is_correct,
        })

    return {
        "accuracy": round(correct / total, 3) if total else 0.0,
        "correct": correct,
        "total": total,
        "details": details,
    }


def score_conditions(golden: Dict, extracted: Dict) -> Dict[str, Any]:
    """Score whether decision conditions are correct on matched decision nodes."""
    g_tree = golden.get("tree", {}).get("start")
    e_tree = extracted.get("tree", {}).get("start")
    if not g_tree or not e_tree:
        return {"error": "Missing tree"}

    g_flat = flatten_tree(g_tree)
    e_flat = flatten_tree(e_tree)
    node_matches = match_nodes(g_flat, e_flat)

    correct = 0
    total = 0
    details: List[Dict[str, Any]] = []

    for g, e, _ in node_matches:
        if e is None or g["type"] != "decision":
            continue
        g_cond = g.get("condition")
        if not g_cond:
            continue
        total += 1
        e_cond = e.get("condition")
        if not e_cond:
            details.append({
                "node": g["label"],
                "golden_condition": g_cond,
                "extracted_condition": None,
                "correct": False,
            })
            continue

        # Check comparator+value match, allowing inverted pairs
        # (e.g. gt 5 ≡ lte 5 with swapped children — same decision)
        is_correct = _conditions_equivalent(g_cond, e_cond)

        if is_correct:
            correct += 1
        details.append({
            "node": g["label"],
            "golden_condition": g_cond,
            "extracted_condition": e_cond,
            "correct": is_correct,
        })

    return {
        "accuracy": round(correct / total, 3) if total else 0.0,
        "correct": correct,
        "total": total,
        "details": details,
    }


def _values_equivalent(a: Any, b: Any) -> bool:
    """Check if two condition values are equivalent, handling numeric strings."""
    if a == b:
        return True
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        pass
    if isinstance(a, str) and isinstance(b, str):
        return _normalise_label(a) == _normalise_label(b)
    return False


# Comparator pairs that are inverses of each other (same decision, swapped children)
_INVERTED_COMPARATORS = {
    "gt": "lte", "lte": "gt",
    "gte": "lt", "lt": "gte",
    "is_true": "is_false", "is_false": "is_true",
}


def _conditions_equivalent(g: Dict, e: Dict) -> bool:
    """Check if two conditions are equivalent, including inverted comparators.

    gt(5) and lte(5) represent the same branching point with swapped children,
    so both are considered correct."""
    g_comp = g.get("comparator", "")
    e_comp = e.get("comparator", "")
    g_val = g.get("value")
    e_val = e.get("value")

    # Direct match
    if g_comp == e_comp and _values_equivalent(g_val, e_val):
        return True
    # Inverted match (same threshold, opposite comparator)
    if _INVERTED_COMPARATORS.get(g_comp) == e_comp and _values_equivalent(g_val, e_val):
        return True
    # enum_eq is its own thing — just check value
    if g_comp == "enum_eq" and e_comp == "enum_eq":
        return _values_equivalent(g_val, e_val)
    return False


def score_outputs(golden: Dict, extracted: Dict) -> Dict[str, Any]:
    """Score how well the declared outputs match."""
    g_outs = golden.get("outputs", [])
    e_outs = extracted.get("outputs", [])

    matched = 0
    used: set[int] = set()
    details: List[Dict[str, Any]] = []

    for go in g_outs:
        best_score = 0.0
        best_idx = -1
        for ei, eo in enumerate(e_outs):
            if ei in used:
                continue
            sim = label_similarity(go["name"], eo["name"])
            if sim > best_score:
                best_score = sim
                best_idx = ei
        if best_score >= 0.55 and best_idx >= 0:
            matched += 1
            used.add(best_idx)
            details.append({
                "golden": go["name"],
                "extracted": e_outs[best_idx]["name"],
                "similarity": round(best_score, 3),
            })
        else:
            details.append({
                "golden": go["name"],
                "extracted": None,
                "similarity": 0.0,
            })

    total_golden = len(g_outs)
    total_extracted = len(e_outs)
    precision = matched / total_extracted if total_extracted else 0.0
    recall = matched / total_golden if total_golden else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "golden_count": total_golden,
        "extracted_count": total_extracted,
        "matched": matched,
        "details": details,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  5. Aggregate scoring
# ═══════════════════════════════════════════════════════════════════════════

def compute_scores(golden: Dict, extracted: Dict) -> Dict[str, Any]:
    """Run all scoring dimensions and compute an overall score."""
    scores = {
        "variables": score_variables(golden, extracted),
        "tree_nodes": score_tree_nodes(golden, extracted),
        "topology": score_topology(golden, extracted),
        "conditions": score_conditions(golden, extracted),
        "outputs": score_outputs(golden, extracted),
    }

    # Weighted overall score
    weights = {
        "variables": 0.15,       # Did it identify the right inputs?
        "tree_nodes": 0.30,      # Did it find the right nodes?
        "topology": 0.25,        # Are parent-child links correct?
        "conditions": 0.15,      # Are decision conditions correct?
        "outputs": 0.15,         # Did it identify the right outputs?
    }
    overall = 0.0
    for key, weight in weights.items():
        dim = scores[key]
        # Use F1 for precision/recall dims, accuracy for others
        if "f1" in dim:
            overall += dim["f1"] * weight
        elif "accuracy" in dim:
            overall += dim["accuracy"] * weight

    scores["overall"] = round(overall, 3)
    scores["weights"] = weights
    return scores


# ═══════════════════════════════════════════════════════════════════════════
#  6. Report printer
# ═══════════════════════════════════════════════════════════════════════════

def print_report(scores: Dict[str, Any], run_idx: Optional[int] = None) -> None:
    """Print a human-readable accuracy report."""
    header = "EVAL REPORT"
    if run_idx is not None:
        header += f" (Run {run_idx})"
    print(f"\n{'=' * 60}")
    print(f"  {header}")
    print(f"{'=' * 60}")

    # Variables
    v = scores["variables"]
    print(f"\n  VARIABLES (weight={scores['weights']['variables']:.0%})")
    print(f"    Precision:     {v['precision']:.1%}  ({v['matched']}/{v['extracted_count']} extracted)")
    print(f"    Recall:        {v['recall']:.1%}  ({v['matched']}/{v['golden_count']} golden)")
    print(f"    F1:            {v['f1']:.1%}")
    print(f"    Type accuracy: {v['type_accuracy']:.1%}")
    for d in v["details"]:
        status = "MATCH" if d.get("extracted") else "MISS"
        typ = f" type={'OK' if d.get('type_match') else 'WRONG'}" if d.get("extracted") else ""
        print(f"      [{status}] {d['golden']:40s} -> {d.get('extracted') or '???':40s}{typ}")

    # Tree nodes
    t = scores["tree_nodes"]
    print(f"\n  TREE NODES (weight={scores['weights']['tree_nodes']:.0%})")
    print(f"    Precision:          {t['precision']:.1%}  ({t['matched']}/{t['extracted_count']})")
    print(f"    Recall:             {t['recall']:.1%}  ({t['matched']}/{t['golden_count']})")
    print(f"    F1:                 {t['f1']:.1%}")
    print(f"    Type accuracy:      {t['type_accuracy']:.1%}")
    print(f"    Edge label accuracy: {t['edge_label_accuracy']:.1%}")

    # Topology
    tp = scores["topology"]
    print(f"\n  TOPOLOGY (weight={scores['weights']['topology']:.0%})")
    print(f"    Accuracy: {tp['accuracy']:.1%}  ({tp['correct']}/{tp['total']})")

    # Conditions
    c = scores["conditions"]
    print(f"\n  CONDITIONS (weight={scores['weights']['conditions']:.0%})")
    print(f"    Accuracy: {c['accuracy']:.1%}  ({c['correct']}/{c['total']})")
    for d in c.get("details", []):
        status = "OK" if d["correct"] else "WRONG"
        print(f"      [{status}] {d['node']}")

    # Outputs
    o = scores["outputs"]
    print(f"\n  OUTPUTS (weight={scores['weights']['outputs']:.0%})")
    print(f"    Precision: {o['precision']:.1%}  ({o['matched']}/{o['extracted_count']})")
    print(f"    Recall:    {o['recall']:.1%}  ({o['matched']}/{o['golden_count']})")
    print(f"    F1:        {o['f1']:.1%}")

    # Overall
    print(f"\n  {'─' * 40}")
    print(f"  OVERALL SCORE:  {scores['overall']:.1%}")
    print(f"{'=' * 60}\n")


# ═══════════════════════════════════════════════════════════════════════════
#  7. Main
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate workflow extraction accuracy")
    parser.add_argument("--image", default="workflow_test.jpeg",
                        help="Image filename (relative to project root)")
    parser.add_argument("--golden", default=None,
                        help="Golden JSON path (auto-detected from image name if omitted)")
    parser.add_argument("--runs", type=int, default=1,
                        help="Number of extraction runs (for consistency measurement)")
    parser.add_argument("--save", default=None,
                        help="Save extracted JSON to this path (for inspection)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print detailed node-by-node comparison")
    args = parser.parse_args()

    # Resolve paths
    image_path = IMAGE_DIR / args.image
    if not image_path.exists():
        logger.error("Image not found: %s", image_path)
        sys.exit(1)

    if args.golden:
        golden_path = Path(args.golden)
    else:
        stem = image_path.stem  # e.g. "workflow_test"
        golden_path = GOLDEN_DIR / f"{stem}.json"
    if not golden_path.exists():
        logger.error("Golden solution not found: %s", golden_path)
        sys.exit(1)

    # Load golden and normalize it the same way extraction output is normalized
    with open(golden_path) as f:
        golden_raw = json.load(f)
    # Remove _meta (not part of the extraction output)
    golden_raw.pop("_meta", None)
    golden = normalize_analysis(dict(golden_raw))

    logger.info("Image:  %s", image_path)
    logger.info("Golden: %s", golden_path)
    logger.info("Runs:   %d", args.runs)

    all_scores: List[Dict[str, Any]] = []
    for i in range(args.runs):
        logger.info("─── Run %d/%d ───", i + 1, args.runs)
        extracted = run_extraction(image_path)

        if args.save:
            save_path = Path(args.save)
            if args.runs > 1:
                save_path = save_path.with_stem(f"{save_path.stem}_run{i+1}")
            with open(save_path, "w") as f:
                json.dump(extracted, f, indent=2)
            logger.info("Saved extraction to %s", save_path)

        scores = compute_scores(golden, extracted)
        all_scores.append(scores)
        print_report(scores, run_idx=i + 1 if args.runs > 1 else None)

    # Summary across runs
    if args.runs > 1:
        overall_scores = [s["overall"] for s in all_scores]
        avg = sum(overall_scores) / len(overall_scores)
        mn = min(overall_scores)
        mx = max(overall_scores)
        print(f"\n{'=' * 60}")
        print(f"  SUMMARY ({args.runs} runs)")
        print(f"{'=' * 60}")
        print(f"    Average overall: {avg:.1%}")
        print(f"    Min:             {mn:.1%}")
        print(f"    Max:             {mx:.1%}")
        print(f"    Spread:          {mx - mn:.1%}")
        print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
