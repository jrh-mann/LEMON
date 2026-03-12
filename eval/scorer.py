"""Scorer: compare extracted workflows against golden solutions.

Scores across 6 dimensions:
  1. Variables   — input variable recall + type accuracy
  2. Nodes       — node recall + type accuracy
  3. Topology    — edge recall + label accuracy (via node mapping)
  4. Conditions  — decision node comparator + value accuracy
  5. Outputs     — end node output_value similarity
  6. Functional  — execution-based routing agreement (same inputs → same end node)

Usage (standalone):
    python -m eval.scorer eval/logs/20260312T*.json
    python -m eval.scorer some_log.json --golden fixtures/golden_liver_pathology.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Fuzzy matching threshold — labels must be at least this similar.
_FUZZY_THRESHOLD = 0.55


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class DimensionScore:
    """Result for one scoring dimension."""

    name: str
    score: float  # 0.0–1.0
    matched: int  # items matched from golden
    total: int  # total items in golden
    detail: str = ""  # human-readable breakdown


@dataclass
class ScoreResult:
    """Complete scoring result across all 6 dimensions."""

    variables: DimensionScore
    nodes: DimensionScore
    topology: DimensionScore
    conditions: DimensionScore
    outputs: DimensionScore
    functional: DimensionScore

    @property
    def overall(self) -> float:
        """Simple average of all 6 dimension scores."""
        return (
            self.variables.score
            + self.nodes.score
            + self.topology.score
            + self.conditions.score
            + self.outputs.score
            + self.functional.score
        ) / 6

    def summary_dict(self) -> Dict[str, Any]:
        """Flat dict for CSV/JSON serialization."""
        return {
            "score_overall": round(self.overall, 3),
            "score_variables": round(self.variables.score, 3),
            "score_nodes": round(self.nodes.score, 3),
            "score_topology": round(self.topology.score, 3),
            "score_conditions": round(self.conditions.score, 3),
            "score_outputs": round(self.outputs.score, 3),
            "score_functional": round(self.functional.score, 3),
        }


# ---------------------------------------------------------------------------
# Fuzzy matching helpers
# ---------------------------------------------------------------------------


def _normalize(s: str) -> str:
    """Lowercase, strip non-alphanumeric (except spaces) for fuzzy matching."""
    if not s:
        return ""
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def _fuzzy_ratio(a: str, b: str) -> float:
    """Similarity ratio between two strings (0.0–1.0)."""
    na, nb = _normalize(a), _normalize(b)
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


# ---------------------------------------------------------------------------
# Node mapping: golden_id → extracted_id
# ---------------------------------------------------------------------------


def _build_node_map(
    golden_nodes: List[Dict[str, Any]],
    extracted_nodes: List[Dict[str, Any]],
) -> Dict[str, str]:
    """Greedy 1:1 mapping from golden node IDs to extracted node IDs.

    Matches by label similarity. Prefers same-type matches when scores tie.
    """
    # Compute all pairwise (golden_idx, extracted_idx, similarity, same_type).
    candidates: List[Tuple[int, int, float, bool]] = []
    for gi, gn in enumerate(golden_nodes):
        g_label = gn.get("label", "")
        g_type = gn.get("type", "")
        for ei, en in enumerate(extracted_nodes):
            sim = _fuzzy_ratio(g_label, en.get("label", ""))
            same_type = g_type == en.get("type", "")
            candidates.append((gi, ei, sim, same_type))

    # Sort: highest similarity first, then prefer same-type on ties.
    candidates.sort(key=lambda c: (c[2], c[3]), reverse=True)

    used_golden: set[int] = set()
    used_extracted: set[int] = set()
    node_map: Dict[str, str] = {}

    for gi, ei, sim, _same_type in candidates:
        if sim < _FUZZY_THRESHOLD:
            break  # remaining are all below threshold
        if gi in used_golden or ei in used_extracted:
            continue
        g_id = golden_nodes[gi].get("id", "")
        e_id = extracted_nodes[ei].get("id", extracted_nodes[ei].get("node_id", ""))
        node_map[g_id] = e_id
        used_golden.add(gi)
        used_extracted.add(ei)

    return node_map


# ---------------------------------------------------------------------------
# Dimension 1: Variables
# ---------------------------------------------------------------------------


def _score_variables(
    golden: Dict[str, Any],
    extracted: Dict[str, Any],
) -> DimensionScore:
    """Match variables by name, check type correctness."""
    g_vars = golden.get("variables", [])
    e_vars = extracted.get("variables", [])

    if not g_vars:
        return DimensionScore("variables", 1.0, 0, 0, "no golden variables")

    matched = 0
    type_correct = 0
    details: List[str] = []
    used: set[int] = set()

    for gv in g_vars:
        best_idx: Optional[int] = None
        best_score = 0.0

        for i, ev in enumerate(e_vars):
            if i in used:
                continue
            # Match by name primarily, description as fallback.
            name_sim = _fuzzy_ratio(gv.get("name", ""), ev.get("name", ""))
            desc_sim = _fuzzy_ratio(
                gv.get("description", ""), ev.get("description", "")
            )
            combined = max(name_sim, desc_sim * 0.8)
            if combined > best_score:
                best_score = combined
                best_idx = i

        if best_idx is not None and best_score >= 0.5:
            used.add(best_idx)
            ev = e_vars[best_idx]
            matched += 1
            if gv.get("type") == ev.get("type"):
                type_correct += 1
                details.append(f"  ok {gv['name']} -> {ev.get('name')} (type OK)")
            else:
                details.append(
                    f"  ~  {gv['name']} -> {ev.get('name')} "
                    f"(type: {gv.get('type')} vs {ev.get('type')})"
                )
        else:
            details.append(f"  x  {gv['name']} — NOT FOUND")

    extra = len(e_vars) - len(used)
    if extra > 0:
        details.append(f"  +  {extra} extra variable(s) in extraction")

    # Score: 50% recall, 50% type accuracy.
    recall = matched / len(g_vars)
    type_acc = type_correct / len(g_vars)
    score = 0.5 * recall + 0.5 * type_acc

    return DimensionScore(
        "variables", score, matched, len(g_vars), "\n".join(details)
    )


# ---------------------------------------------------------------------------
# Dimension 2: Nodes
# ---------------------------------------------------------------------------


def _score_nodes(
    golden: Dict[str, Any],
    extracted: Dict[str, Any],
    node_map: Dict[str, str],
) -> DimensionScore:
    """Score node recall and type accuracy via the node mapping."""
    g_nodes = golden.get("nodes", [])
    e_lookup = {
        n.get("id", n.get("node_id", "")): n for n in extracted.get("nodes", [])
    }

    if not g_nodes:
        return DimensionScore("nodes", 1.0, 0, 0, "no golden nodes")

    matched = 0
    type_correct = 0
    details: List[str] = []

    for gn in g_nodes:
        e_id = node_map.get(gn["id"])
        if not e_id or e_id not in e_lookup:
            details.append(f"  x  [{gn['type']}] {gn['label'][:50]} — NOT MAPPED")
            continue

        en = e_lookup[e_id]
        matched += 1
        if gn["type"] == en.get("type"):
            type_correct += 1
            details.append(
                f"  ok [{gn['type']}] {gn['label'][:50]} -> {en.get('label', '')[:50]}"
            )
        else:
            details.append(
                f"  ~  [{gn['type']}->{en.get('type')}] "
                f"{gn['label'][:50]} -> {en.get('label', '')[:50]}"
            )

    extra = len(extracted.get("nodes", [])) - matched
    if extra > 0:
        details.append(f"  +  {extra} extra node(s) in extraction")

    recall = matched / len(g_nodes)
    type_acc = type_correct / len(g_nodes)
    score = 0.5 * recall + 0.5 * type_acc

    return DimensionScore("nodes", score, matched, len(g_nodes), "\n".join(details))


# ---------------------------------------------------------------------------
# Dimension 3: Topology (edges)
# ---------------------------------------------------------------------------


def _normalize_edge_label(label: str) -> str:
    """Normalize edge labels for comparison (Yes->true, No->false, etc.)."""
    s = label.strip().lower()
    if s in ("yes", "y"):
        return "true"
    if s in ("no", "n"):
        return "false"
    return s


def _score_topology(
    golden: Dict[str, Any],
    extracted: Dict[str, Any],
    node_map: Dict[str, str],
) -> DimensionScore:
    """Score edge recall and label accuracy via the node mapping."""
    g_edges = golden.get("edges", [])
    e_edges = extracted.get("edges", [])

    if not g_edges:
        return DimensionScore("topology", 1.0, 0, 0, "no golden edges")

    # Build extracted edge lookup: (from_id, to_id) -> set of labels.
    e_edge_labels: Dict[Tuple[str, str], set[str]] = {}
    for ee in e_edges:
        fr = ee.get("from") or ee.get("source", "")
        to = ee.get("to") or ee.get("target", "")
        label = _normalize_edge_label(ee.get("label", ""))
        e_edge_labels.setdefault((fr, to), set()).add(label)

    matched = 0
    label_correct = 0
    details: List[str] = []

    for ge in g_edges:
        g_from, g_to = ge["from"], ge["to"]
        g_label = _normalize_edge_label(ge.get("label", ""))

        # Map golden IDs to extracted IDs.
        e_from = node_map.get(g_from)
        e_to = node_map.get(g_to)

        if not e_from or not e_to:
            details.append(
                f"  x  {g_from} -> {g_to} [{g_label}] — unmapped node(s)"
            )
            continue

        labels = e_edge_labels.get((e_from, e_to))
        if labels is not None:
            matched += 1
            if g_label in labels or not g_label:
                label_correct += 1
                details.append(f"  ok {g_from} -> {g_to} [{g_label}]")
            else:
                details.append(
                    f"  ~  {g_from} -> {g_to} [{g_label}] — edge OK, label wrong"
                )
        else:
            details.append(f"  x  {g_from} -> {g_to} [{g_label}] — edge MISSING")

    extra = len(e_edges) - matched
    if extra > 0:
        details.append(f"  +  {extra} extra edge(s) in extraction")

    # 60% weight on edge recall, 40% on label accuracy.
    recall = matched / len(g_edges)
    label_acc = label_correct / len(g_edges)
    score = 0.6 * recall + 0.4 * label_acc

    return DimensionScore(
        "topology", score, matched, len(g_edges), "\n".join(details)
    )


# ---------------------------------------------------------------------------
# Dimension 4: Conditions
# ---------------------------------------------------------------------------


def _score_conditions(
    golden: Dict[str, Any],
    extracted: Dict[str, Any],
    node_map: Dict[str, str],
) -> DimensionScore:
    """Score condition accuracy on decision nodes."""
    g_decisions = {
        n["id"]: n for n in golden.get("nodes", []) if n.get("condition")
    }
    e_lookup = {
        n.get("id", n.get("node_id", "")): n for n in extracted.get("nodes", [])
    }

    if not g_decisions:
        return DimensionScore("conditions", 1.0, 0, 0, "no conditions in golden")

    has_condition = 0
    comparator_correct = 0
    value_correct = 0
    details: List[str] = []

    for gid, gn in g_decisions.items():
        eid = node_map.get(gid)
        if not eid or eid not in e_lookup:
            details.append(f"  x  {gn['label'][:40]} — node not mapped")
            continue

        en = e_lookup[eid]
        ec = en.get("condition")
        gc = gn["condition"]

        if not ec:
            details.append(
                f"  x  {gn['label'][:40]} — no condition on extracted node"
            )
            continue

        has_condition += 1

        # Check comparator.
        g_comp = gc.get("comparator", "")
        e_comp = ec.get("comparator", "")
        comp_ok = g_comp == e_comp
        if comp_ok:
            comparator_correct += 1

        # Check value (with tolerance for numeric).
        g_val = gc.get("value")
        e_val = ec.get("value")
        val_ok = _values_match(g_val, e_val)
        if val_ok:
            value_correct += 1

        status = "ok" if (comp_ok and val_ok) else "~ "
        detail = f"  {status} {gn['label'][:40]}: {g_comp}"
        if g_val is not None:
            detail += f" {g_val}"
        if not comp_ok:
            detail += f" (got comp: {e_comp})"
        if not val_ok:
            detail += f" (got val: {e_val})"
        details.append(detail)

    total = len(g_decisions)
    # Weighted: 30% has condition, 35% comparator, 35% value.
    score = (
        0.3 * (has_condition / total)
        + 0.35 * (comparator_correct / total)
        + 0.35 * (value_correct / total)
    )

    return DimensionScore(
        "conditions", score, has_condition, total, "\n".join(details)
    )


def _values_match(golden_val: Any, extracted_val: Any) -> bool:
    """Compare condition values, with 5% tolerance for numeric types."""
    if golden_val is None and extracted_val is None:
        return True
    if golden_val is None or extracted_val is None:
        return False
    # Numeric tolerance.
    if isinstance(golden_val, (int, float)) and isinstance(extracted_val, (int, float)):
        if golden_val == 0:
            return extracted_val == 0
        return abs(golden_val - extracted_val) / abs(golden_val) <= 0.05
    # Exact match for strings/enums.
    return str(golden_val).lower().strip() == str(extracted_val).lower().strip()


# ---------------------------------------------------------------------------
# Dimension 5: Outputs
# ---------------------------------------------------------------------------


def _score_outputs(
    golden: Dict[str, Any],
    extracted: Dict[str, Any],
    node_map: Dict[str, str],
) -> DimensionScore:
    """Score end node output_value similarity."""
    g_ends = [n for n in golden.get("nodes", []) if n["type"] == "end"]
    e_lookup = {
        n.get("id", n.get("node_id", "")): n for n in extracted.get("nodes", [])
    }

    if not g_ends:
        return DimensionScore("outputs", 1.0, 0, 0, "no end nodes in golden")

    matched = 0
    output_correct = 0
    details: List[str] = []

    for gn in g_ends:
        eid = node_map.get(gn["id"])
        if not eid or eid not in e_lookup:
            details.append(f"  x  {gn['label'][:40]} — not mapped")
            continue

        en = e_lookup[eid]
        matched += 1

        g_out = str(gn.get("output_value", ""))
        e_out = str(en.get("output_value", ""))

        sim = _fuzzy_ratio(g_out, e_out)
        if sim >= 0.5:
            output_correct += 1
            details.append(f"  ok {gn['label'][:40]}")
        else:
            details.append(
                f"  ~  {gn['label'][:40]}: "
                f"expected '{g_out[:30]}' got '{e_out[:30]}'"
            )

    total = len(g_ends)
    recall = matched / total
    out_acc = output_correct / total
    score = 0.5 * recall + 0.5 * out_acc

    return DimensionScore("outputs", score, matched, total, "\n".join(details))


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def score(golden: Dict[str, Any], extracted: Dict[str, Any]) -> ScoreResult:
    """Score an extracted workflow against a golden solution.

    Args:
        golden: Golden solution dict with nodes, edges, variables, outputs.
        extracted: Extracted workflow dict with same structure.

    Returns:
        ScoreResult with per-dimension scores and overall average.
    """
    from .functional import functional_score

    g_nodes = golden.get("nodes", [])
    e_nodes = extracted.get("nodes", [])
    node_map = _build_node_map(g_nodes, e_nodes)

    # Functional scoring: execute both workflows with same inputs.
    func_result = functional_score(golden, extracted)
    func_dim = DimensionScore(
        name="functional",
        score=func_result.score,
        matched=func_result.cases_matched,
        total=func_result.cases_tested,
        detail=func_result.detail,
    )

    return ScoreResult(
        variables=_score_variables(golden, extracted),
        nodes=_score_nodes(golden, extracted, node_map),
        topology=_score_topology(golden, extracted, node_map),
        conditions=_score_conditions(golden, extracted, node_map),
        outputs=_score_outputs(golden, extracted, node_map),
        functional=func_dim,
    )


# ---------------------------------------------------------------------------
# Standalone CLI: re-score saved eval logs
# ---------------------------------------------------------------------------


def score_from_log(log_path: Path, golden_path: Path) -> ScoreResult:
    """Load a saved eval log and score it against a golden solution."""
    log_data = json.loads(log_path.read_text())
    golden = json.loads(golden_path.read_text())
    workflow = log_data.get("workflow", {})
    return score(golden, workflow)


def _find_golden_for_log(log_path: Path) -> Optional[Path]:
    """Auto-detect the golden file for a saved eval log."""
    log_data = json.loads(log_path.read_text())
    sample_name = log_data.get("sample_name", "")
    if not sample_name:
        return None
    # Look in fixtures/ relative to repo root.
    repo_root = Path(__file__).resolve().parent.parent
    golden_path = repo_root / "fixtures" / f"golden_{sample_name}.json"
    return golden_path if golden_path.exists() else None


def _cli_main() -> None:
    """Standalone CLI for re-scoring saved eval logs."""
    parser = argparse.ArgumentParser(
        description="Score eval logs against golden solutions",
    )
    parser.add_argument(
        "logs", nargs="+", type=str,
        help="Paths to eval log JSON files",
    )
    parser.add_argument(
        "--golden", type=str, default=None,
        help="Override golden solution path (applies to all logs)",
    )
    args = parser.parse_args()

    results: List[Dict[str, Any]] = []

    for log_str in args.logs:
        log_path = Path(log_str)
        if not log_path.exists():
            print(f"SKIP: {log_str} — file not found")
            continue

        # Skip error runs (tiny files with no workflow).
        log_data = json.loads(log_path.read_text())
        if log_data.get("error") or not log_data.get("workflow", {}).get("nodes"):
            print(f"SKIP: {log_path.name} — error or empty workflow")
            continue

        if args.golden:
            golden_path = Path(args.golden)
        else:
            golden_path = _find_golden_for_log(log_path)

        if not golden_path or not golden_path.exists():
            print(f"SKIP: {log_path.name} — no golden solution found")
            continue

        result = score_from_log(log_path, golden_path)
        sample = log_data.get("sample_name", "?")
        model = log_data.get("model", "?")

        print(f"\n{log_path.name}")
        print(f"  Sample: {sample}  Model: {model}")
        for dim in [result.variables, result.nodes, result.topology,
                     result.conditions, result.outputs, result.functional]:
            print(f"  {dim.name:<12} {dim.score:5.1%}  ({dim.matched}/{dim.total})")
        print(f"  {'OVERALL':<12} {result.overall:5.1%}")

        results.append({
            "file": log_path.name, "sample": sample, "model": model,
            **result.summary_dict(),
        })

    # Summary table.
    if len(results) > 1:
        print(f"\n{'='*106}")
        print(f"{'File':<65} {'Vars':>5} {'Node':>5} {'Topo':>5} "
              f"{'Cond':>5} {'Out':>5} {'Func':>5} {'AVG':>5}")
        print("-" * 106)
        for r in results:
            print(
                f"{r['file']:<65} "
                f"{r['score_variables']:>5.0%} {r['score_nodes']:>5.0%} "
                f"{r['score_topology']:>5.0%} {r['score_conditions']:>5.0%} "
                f"{r['score_outputs']:>5.0%} {r['score_functional']:>5.0%} "
                f"{r['score_overall']:>5.0%}"
            )
        avg = sum(r["score_overall"] for r in results) / len(results)
        print(f"\n  Grand Average: {avg:.1%} across {len(results)} runs")


if __name__ == "__main__":
    _cli_main()
