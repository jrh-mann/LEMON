"""Functional scoring: execute both golden and extracted workflows with
the same inputs, compare which end node they route to.

Unlike structural scoring (does the graph look the same?), functional
scoring answers: does the workflow *behave* the same?  Two workflows
that are architecturally different but route every patient to the same
outcome get a perfect functional score.

Usage (standalone):
    python -m eval.functional fixtures/golden_lipid_management.json eval/logs/some_run.json
"""

from __future__ import annotations

import itertools
import logging
import random
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Set, Tuple

from src.backend.execution.interpreter import TreeInterpreter
from src.backend.utils.flowchart import tree_from_flowchart

logger = logging.getLogger("eval.functional")

# Max test cases before random sampling to keep runtime bounded.
_MAX_CASES = 200

# Fuzzy threshold for matching end node labels between golden and extracted.
_END_NODE_MATCH_THRESHOLD = 0.55


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class FunctionalScore:
    """Result of functional (execution-based) scoring."""

    score: float  # 0.0–1.0 — fraction of test cases with matching routing
    cases_tested: int
    cases_matched: int
    cases_golden_failed: int  # golden workflow errored (excluded from score)
    cases_extracted_failed: int  # extracted errored on valid golden inputs
    detail: str = ""  # human-readable per-case breakdown


# ---------------------------------------------------------------------------
# Test case generation
# ---------------------------------------------------------------------------


def _extract_thresholds(golden: Dict[str, Any]) -> Dict[str, List[float]]:
    """Scan all conditions in golden for numeric threshold values.

    Returns {variable_id: [threshold_values]} so we can generate
    boundary test inputs (below, at, above each threshold).
    """
    thresholds: Dict[str, List[float]] = {}

    for node in golden.get("nodes", []):
        cond = node.get("condition")
        if not cond:
            continue

        # Handle compound conditions (AND/OR) by flattening.
        sub_conditions = _flatten_conditions(cond)

        for sc in sub_conditions:
            input_id = sc.get("input_id", "")
            value = sc.get("value")
            value2 = sc.get("value2")

            if input_id and isinstance(value, (int, float)):
                thresholds.setdefault(input_id, []).append(float(value))
            if input_id and isinstance(value2, (int, float)):
                thresholds.setdefault(input_id, []).append(float(value2))

    return thresholds


def _flatten_conditions(cond: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten a possibly compound condition into simple conditions."""
    if "operator" in cond:
        # Compound: recurse into sub-conditions.
        result = []
        for sub in cond.get("conditions", []):
            result.extend(_flatten_conditions(sub))
        return result
    return [cond]


def _generate_test_cases(golden: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate targeted test inputs from golden variables and conditions.

    Strategy:
    - bool: [True, False]
    - number: boundary values derived from conditions (below/at/above each
      threshold) plus a default range if no conditions reference the variable
    - enum: each enum_value
    - Combinatorial product of all variables, capped at _MAX_CASES.
    """
    variables = golden.get("variables", [])
    thresholds = _extract_thresholds(golden)

    # Build per-variable value sets.
    var_values: Dict[str, List[Any]] = {}

    for var in variables:
        var_id = var["id"]
        var_type = var.get("type", "string")
        source = var.get("source", "input")

        # Skip non-input variables (subprocess/calculated are runtime-derived).
        if source not in ("input",):
            continue

        if var_type == "bool":
            var_values[var_id] = [True, False]

        elif var_type == "number":
            vals: Set[float] = set()
            # Get thresholds from conditions that reference this variable.
            for t in thresholds.get(var_id, []):
                # Test just below, at, and just above each threshold.
                vals.add(t - 0.1)
                vals.add(t)
                vals.add(t + 0.1)
            if not vals:
                # No conditions reference this variable — use sensible defaults.
                vals = {0, 5, 10, 50}
            var_values[var_id] = sorted(vals)

        elif var_type == "enum":
            enum_vals = var.get("enum_values", [])
            if enum_vals:
                var_values[var_id] = list(enum_vals)
            else:
                # No enum values defined — skip (can't generate meaningful inputs).
                var_values[var_id] = ["unknown"]

        else:
            # string or other — use a placeholder.
            var_values[var_id] = ["test_value"]

    if not var_values:
        return []

    # Combinatorial product of all variable values.
    var_ids = list(var_values.keys())
    value_lists = [var_values[vid] for vid in var_ids]
    all_combos = list(itertools.product(*value_lists))

    # Cap at _MAX_CASES with random sampling.
    if len(all_combos) > _MAX_CASES:
        random.seed(42)  # Deterministic sampling for reproducibility.
        all_combos = random.sample(all_combos, _MAX_CASES)

    # Convert to list of dicts.
    cases: List[Dict[str, Any]] = []
    for combo in all_combos:
        case = {var_ids[i]: combo[i] for i in range(len(var_ids))}
        cases.append(case)

    return cases


# ---------------------------------------------------------------------------
# Variable ID mapping (golden → extracted)
# ---------------------------------------------------------------------------


def _word_overlap(a: str, b: str) -> float:
    """Jaccard similarity on word tokens — better than SequenceMatcher for
    short variable names where word order varies (e.g. "Treatment Optimised"
    vs "Optimised on Treatment").
    """
    wa = set(_normalize(a).split())
    wb = set(_normalize(b).split())
    if not wa and not wb:
        return 1.0
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _build_variable_map(
    golden: Dict[str, Any],
    extracted: Dict[str, Any],
) -> Dict[str, str]:
    """Map golden variable IDs to extracted variable IDs.

    Returns {golden_var_id: extracted_var_id}.
    Uses combined word-overlap + type match scoring to handle short names
    and word-order differences (e.g. "Treatment Optimised" vs "Optimised
    on Treatment").
    """
    g_vars = golden.get("variables", [])
    e_vars = extracted.get("variables", [])

    if not g_vars or not e_vars:
        return {}

    # Compute pairwise scores: combine word overlap, sequence match, and type.
    candidates: List[Tuple[int, int, float]] = []
    for gi, gv in enumerate(g_vars):
        g_name = gv.get("name", "")
        g_type = gv.get("type", "")
        for ei, ev in enumerate(e_vars):
            e_name = ev.get("name", "")
            e_type = ev.get("type", "")
            # Word overlap handles reordering better than SequenceMatcher.
            word_sim = _word_overlap(g_name, e_name)
            seq_sim = _fuzzy_ratio(g_name, e_name)
            # Best of both methods.
            name_sim = max(word_sim, seq_sim)
            # Type must match — feeding a number to a bool variable causes
            # execution errors. Skip type-mismatched pairs entirely.
            if g_type != e_type:
                continue
            combined = name_sim + 0.2  # Type match bonus.
            candidates.append((gi, ei, combined))

    candidates.sort(key=lambda c: c[2], reverse=True)

    used_g: Set[int] = set()
    used_e: Set[int] = set()
    var_map: Dict[str, str] = {}

    for gi, ei, score in candidates:
        if score < 0.5:
            break
        if gi in used_g or ei in used_e:
            continue
        var_map[g_vars[gi]["id"]] = e_vars[ei]["id"]
        used_g.add(gi)
        used_e.add(ei)

    return var_map


def _translate_inputs(
    case: Dict[str, Any],
    var_map: Dict[str, str],
    extracted: Dict[str, Any],
) -> Dict[str, Any]:
    """Translate golden-keyed inputs to extracted variable IDs.

    Returns the base translated dict WITHOUT extra variable defaults.
    Extra variables are handled separately by _extra_var_combos().
    """
    translated: Dict[str, Any] = {}

    # Map golden inputs → extracted IDs.
    for g_id, value in case.items():
        e_id = var_map.get(g_id)
        if e_id:
            translated[e_id] = value

    return translated


def _extra_var_combos(
    var_map: Dict[str, str],
    extracted: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Generate all value combinations for extracted variables that don't
    exist in the golden (extra variables the LLM invented).

    Returns a list of dicts, each mapping extra_var_id → value.
    If there are no extra variables, returns [{}] (one empty combo).
    Used to give the extracted workflow the benefit of the doubt —
    we try all combos and count a test case as matching if ANY works.
    """
    mapped_e_ids = set(var_map.values())
    extra_vars: Dict[str, List[Any]] = {}

    for var in extracted.get("variables", []):
        var_id = var["id"]
        if var_id in mapped_e_ids:
            continue
        source = var.get("source", "input")
        if source not in ("input",):
            continue  # Skip derived variables.
        var_type = var.get("type", "string")
        if var_type == "bool":
            extra_vars[var_id] = [True, False]
        elif var_type == "number":
            # Use 0 as default — extra number vars are rare and usually
            # don't affect routing as strongly as enums/bools.
            extra_vars[var_id] = [0]
        elif var_type == "enum":
            enum_vals = var.get("enum_values", [])
            extra_vars[var_id] = list(enum_vals) if enum_vals else ["unknown"]
        else:
            extra_vars[var_id] = [""]

    if not extra_vars:
        return [{}]

    # Combinatorial product of extra variables (small: typically 1-3 vars).
    var_ids = list(extra_vars.keys())
    value_lists = [extra_vars[vid] for vid in var_ids]
    combos = list(itertools.product(*value_lists))

    return [
        {var_ids[i]: combo[i] for i in range(len(var_ids))}
        for combo in combos
    ]


# ---------------------------------------------------------------------------
# Workflow execution wrapper
# ---------------------------------------------------------------------------


def _execute_workflow(
    workflow: Dict[str, Any],
    input_values: Dict[str, Any],
) -> Tuple[Optional[str], Optional[str], bool]:
    """Execute a workflow with given inputs and return the end node reached.

    Returns:
        (end_node_id, end_node_label, success)
        On failure: (None, None, False)
    """
    nodes = workflow.get("nodes", [])
    edges = workflow.get("edges", [])
    variables = workflow.get("variables", [])
    outputs = workflow.get("outputs", [])

    if not nodes:
        return (None, None, False)

    try:
        tree = tree_from_flowchart(nodes, edges)
        if not tree:
            return (None, None, False)

        interpreter = TreeInterpreter(
            tree=tree,
            variables=variables,
            outputs=outputs,
        )
        result = interpreter.execute(input_values)

        if result.success and result.path:
            # Last node in path is the end node.
            end_node_id = result.path[-1]
            # Look up label from the node list.
            end_node_label = None
            for node in nodes:
                if node.get("id") == end_node_id:
                    end_node_label = node.get("label", end_node_id)
                    break
            return (end_node_id, end_node_label, True)

        return (None, None, False)

    except Exception as exc:
        logger.debug("Execution failed: %s", exc)
        return (None, None, False)


# ---------------------------------------------------------------------------
# End node matching
# ---------------------------------------------------------------------------


def _normalize(s: str) -> str:
    """Lowercase, strip non-alphanumeric (except spaces) for fuzzy matching."""
    import re
    if not s:
        return ""
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def _fuzzy_ratio(a: str, b: str) -> float:
    """Similarity ratio between two strings (0.0–1.0)."""
    na, nb = _normalize(a), _normalize(b)
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def _build_end_node_map(
    golden: Dict[str, Any],
    extracted: Dict[str, Any],
) -> Dict[str, str]:
    """Fuzzy-match end node labels between golden and extracted.

    Returns {golden_end_node_id: extracted_end_node_id}.
    Uses greedy 1:1 matching by label similarity.
    """
    g_ends = [n for n in golden.get("nodes", []) if n.get("type") == "end"]
    e_ends = [n for n in extracted.get("nodes", []) if n.get("type") == "end"]

    if not g_ends or not e_ends:
        return {}

    # Compute all pairwise similarities.
    candidates: List[Tuple[int, int, float]] = []
    for gi, gn in enumerate(g_ends):
        for ei, en in enumerate(e_ends):
            sim = _fuzzy_ratio(
                gn.get("label", ""),
                en.get("label", ""),
            )
            candidates.append((gi, ei, sim))

    # Sort by similarity descending for greedy matching.
    candidates.sort(key=lambda c: c[2], reverse=True)

    used_golden: Set[int] = set()
    used_extracted: Set[int] = set()
    end_map: Dict[str, str] = {}

    for gi, ei, sim in candidates:
        if sim < _END_NODE_MATCH_THRESHOLD:
            break
        if gi in used_golden or ei in used_extracted:
            continue
        end_map[g_ends[gi]["id"]] = e_ends[ei]["id"]
        used_golden.add(gi)
        used_extracted.add(ei)

    return end_map


# ---------------------------------------------------------------------------
# Functional scoring
# ---------------------------------------------------------------------------


def functional_score(
    golden: Dict[str, Any],
    extracted: Dict[str, Any],
) -> FunctionalScore:
    """Execute both workflows with the same inputs, compare routing.

    For each test case:
    1. Execute golden workflow → get end node
    2. Execute extracted workflow → get end node
    3. Check if they map to the same end node via label matching

    Cases where golden itself fails are excluded (not the extracted
    workflow's fault). Cases where extracted fails but golden succeeds
    count as mismatches.
    """
    test_cases = _generate_test_cases(golden)
    if not test_cases:
        return FunctionalScore(
            score=0.0, cases_tested=0, cases_matched=0,
            cases_golden_failed=0, cases_extracted_failed=0,
            detail="No test cases could be generated",
        )

    # Pre-compute mappings between golden and extracted.
    var_map = _build_variable_map(golden, extracted)

    # Generate all value combinations for extra variables (ones the
    # extracted workflow has that the golden doesn't). We try all combos
    # and count a test case as matched if ANY combo routes correctly.
    extra_combos = _extra_var_combos(var_map, extracted)

    cases_tested = 0
    cases_matched = 0
    golden_failed = 0
    extracted_failed = 0
    details: List[str] = []

    for case in test_cases:
        g_end_id, g_end_label, g_ok = _execute_workflow(golden, case)

        if not g_ok:
            # Golden itself failed — exclude from scoring.
            golden_failed += 1
            details.append(f"  SKIP  golden failed | inputs={_compact_inputs(case)}")
            continue

        cases_tested += 1

        # Translate golden variable IDs to extracted IDs.
        e_base = _translate_inputs(case, var_map, extracted)

        # Try all combinations of extra variable values. Count as match
        # if ANY combination routes to a semantically equivalent end node.
        best_match = False
        best_e_label: Optional[str] = None
        any_succeeded = False

        for extra in extra_combos:
            e_case = {**e_base, **extra}
            e_end_id, e_end_label, e_ok = _execute_workflow(extracted, e_case)

            if not e_ok:
                continue
            any_succeeded = True
            best_e_label = e_end_label

            # Compare end node labels (not mapped IDs) — golden workflows
            # often duplicate end nodes (e.g. 4 "Send LLTA" nodes for
            # different pathways), so strict ID matching is too harsh.
            label_sim = _fuzzy_ratio(g_end_label or "", e_end_label or "")
            if label_sim >= _END_NODE_MATCH_THRESHOLD:
                best_match = True
                best_e_label = e_end_label
                break  # Found a match, no need to try more combos.

        if best_match:
            cases_matched += 1
            details.append(
                f"  OK    both→{g_end_label} | inputs={_compact_inputs(case)}"
            )
        elif not any_succeeded:
            extracted_failed += 1
            details.append(
                f"  FAIL  extracted failed | golden→{g_end_label} | "
                f"inputs={_compact_inputs(case)}"
            )
        else:
            details.append(
                f"  FAIL  golden→{g_end_label} vs extracted→{best_e_label} | "
                f"inputs={_compact_inputs(case)}"
            )

    score = cases_matched / cases_tested if cases_tested > 0 else 0.0

    return FunctionalScore(
        score=score,
        cases_tested=cases_tested,
        cases_matched=cases_matched,
        cases_golden_failed=golden_failed,
        cases_extracted_failed=extracted_failed,
        detail="\n".join(details),
    )


def _compact_inputs(case: Dict[str, Any]) -> str:
    """Short string representation of test inputs for logging."""
    parts = []
    for k, v in case.items():
        # Shorten variable IDs for readability.
        short_key = k.replace("var_", "").replace("_bool", "").replace("_number", "").replace("_enum", "")
        parts.append(f"{short_key}={v}")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Standalone CLI
# ---------------------------------------------------------------------------


def _cli_main() -> None:
    """Score a saved eval log functionally against its golden solution."""
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Functional scoring: execute workflows and compare routing",
    )
    parser.add_argument("golden", type=str, help="Path to golden solution JSON")
    parser.add_argument(
        "extracted", type=str, nargs="?", default=None,
        help="Path to extracted workflow JSON (eval log or raw workflow). "
             "If omitted, scores golden against itself.",
    )
    args = parser.parse_args()

    golden = json.loads(Path(args.golden).read_text())

    if args.extracted:
        ext_data = json.loads(Path(args.extracted).read_text())
        # Support both raw workflow dicts and eval log format.
        extracted = ext_data.get("workflow", ext_data)
    else:
        extracted = golden

    result = functional_score(golden, extracted)

    print(f"Functional Score: {result.score:.1%}")
    print(f"  Cases tested:          {result.cases_tested}")
    print(f"  Cases matched:         {result.cases_matched}")
    print(f"  Golden failures:       {result.cases_golden_failed}")
    print(f"  Extracted failures:    {result.cases_extracted_failed}")
    print(f"\nDetail:")
    print(result.detail)


if __name__ == "__main__":
    _cli_main()
