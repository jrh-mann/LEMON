"""Scoring utilities for image-to-workflow evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import re

from src.backend.execution.interpreter import TreeInterpreter
from src.backend.utils.flowchart import tree_from_flowchart
from src.backend.validation.workflow_validator import WorkflowValidator


WEIGHTS: Dict[str, float] = {
    "node_f1": 0.25,
    "edge_f1": 0.25,
    "variable_f1": 0.15,
    "output_f1": 0.10,
    "semantic_score": 0.20,
    "validity_score": 0.05,
}


_BRANCH_TRUE = {"yes", "y", "true", "t", "1", "pass", "high", "primary"}
_BRANCH_FALSE = {"no", "n", "false", "f", "0", "fail", "low", "secondary"}


@dataclass(frozen=True)
class PRF:
    precision: float
    recall: float
    f1: float
    matched: int
    predicted_total: int
    reference_total: int


def normalize_label(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-z0-9 ]+", "", text)
    return text.strip()


def normalize_branch_label(value: Any) -> str:
    norm = normalize_label(value)
    if norm in _BRANCH_TRUE:
        return "true"
    if norm in _BRANCH_FALSE:
        return "false"
    return norm


def canonicalize_node_type(raw_type: Any) -> str:
    node_type = str(raw_type or "").strip().lower()
    if node_type == "action":
        return "process"
    if node_type == "output":
        return "end"
    return node_type


def _slug_like(value: str) -> str:
    text = normalize_label(value)
    return text.replace(" ", "_")


def _as_set(items: Iterable[Tuple[str, ...]]) -> set[Tuple[str, ...]]:
    return {item for item in items if all(part != "" for part in item)}


def _compute_prf(matched: int, predicted_total: int, reference_total: int) -> PRF:
    precision = matched / predicted_total if predicted_total else 0.0
    recall = matched / reference_total if reference_total else 0.0
    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return PRF(
        precision=precision,
        recall=recall,
        f1=f1,
        matched=matched,
        predicted_total=predicted_total,
        reference_total=reference_total,
    )


def _node_tokens(nodes: Sequence[Mapping[str, Any]]) -> set[Tuple[str, str]]:
    return _as_set(
        (
            canonicalize_node_type(node.get("type")),
            normalize_label(node.get("label")),
        )
        for node in nodes
    )


def _variable_tokens(variables: Sequence[Mapping[str, Any]]) -> set[Tuple[str, str]]:
    return _as_set(
        (
            normalize_label(var.get("name")),
            str(var.get("type", "")).strip().lower(),
        )
        for var in variables
    )


def _output_tokens(outputs: Sequence[Any]) -> set[str]:
    tokens = set()
    for output in outputs:
        if isinstance(output, Mapping):
            tokens.add(normalize_label(output.get("name") or output.get("value") or ""))
        else:
            tokens.add(normalize_label(output))
    tokens.discard("")
    return tokens


def _edge_tokens(
    edges: Sequence[Mapping[str, Any]],
    id_to_label: Mapping[str, str],
) -> set[Tuple[str, str, str]]:
    tokens: set[Tuple[str, str, str]] = set()
    for edge in edges:
        src_id = edge.get("from") or edge.get("source")
        dst_id = edge.get("to") or edge.get("target")
        src_label = normalize_label(id_to_label.get(str(src_id), ""))
        dst_label = normalize_label(id_to_label.get(str(dst_id), ""))
        branch = normalize_branch_label(edge.get("label", ""))
        if src_label and dst_label:
            tokens.add((src_label, dst_label, branch))
    return tokens


def _node_detail_counts(
    pred_nodes: Sequence[Mapping[str, Any]],
    ref_nodes: Sequence[Mapping[str, Any]],
) -> Dict[str, int]:
    pred_by_type: Dict[str, set[str]] = {}
    ref_by_type: Dict[str, set[str]] = {}

    for node in pred_nodes:
        node_type = canonicalize_node_type(node.get("type"))
        pred_by_type.setdefault(node_type, set()).add(normalize_label(node.get("label")))
    for node in ref_nodes:
        node_type = canonicalize_node_type(node.get("type"))
        ref_by_type.setdefault(node_type, set()).add(normalize_label(node.get("label")))

    label_mismatch_count = 0
    type_overlap_count = 0
    for node_type in set(pred_by_type) | set(ref_by_type):
        pred_labels = pred_by_type.get(node_type, set())
        ref_labels = ref_by_type.get(node_type, set())
        overlap_capacity = min(len(pred_labels), len(ref_labels))
        exact_overlap = len(pred_labels & ref_labels)
        type_overlap_count += overlap_capacity
        label_mismatch_count += max(0, overlap_capacity - exact_overlap)

    return {
        "node_label_mismatch_count": label_mismatch_count,
        "node_type_overlap_count": type_overlap_count,
    }


def _edge_detail_counts(
    pred_edges: Sequence[Mapping[str, Any]],
    ref_edges: Sequence[Mapping[str, Any]],
    pred_id_to_label: Mapping[str, str],
    ref_id_to_label: Mapping[str, str],
) -> Dict[str, int]:
    pred_tokens = _edge_tokens(pred_edges, pred_id_to_label)
    ref_tokens = _edge_tokens(ref_edges, ref_id_to_label)

    pred_pairs = {(src, dst) for src, dst, _ in pred_tokens}
    ref_pairs = {(src, dst) for src, dst, _ in ref_tokens}
    ref_pairs_reversed = {(dst, src) for src, dst in ref_pairs}

    direction_mismatch = len({pair for pair in pred_pairs if pair in ref_pairs_reversed and pair not in ref_pairs})

    label_mismatch = 0
    ref_by_pair: Dict[Tuple[str, str], set[str]] = {}
    for src, dst, branch in ref_tokens:
        ref_by_pair.setdefault((src, dst), set()).add(branch)
    for src, dst, branch in pred_tokens:
        branches = ref_by_pair.get((src, dst))
        if branches and branch not in branches:
            label_mismatch += 1

    return {
        "edge_direction_mismatch_count": direction_mismatch,
        "edge_label_mismatch_count": label_mismatch,
    }


def _infer_defaults_for_variables(variables: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {}
    for var in variables:
        var_id = str(var.get("id") or "")
        var_type = str(var.get("type") or "").lower()
        if not var_id:
            continue
        if var_type in {"int", "float"}:
            defaults[var_id] = 0
        elif var_type == "bool":
            defaults[var_id] = False
        elif var_type == "enum":
            enum_values = var.get("enum_values") or []
            defaults[var_id] = enum_values[0] if enum_values else ""
        else:
            defaults[var_id] = ""
    return defaults


def _match_ground_truth_inputs_to_predicted_ids(
    gt_inputs: Mapping[str, Any],
    predicted_variables: Sequence[Mapping[str, Any]],
) -> Dict[str, str]:
    mapping: Dict[str, str] = {}

    normalized_gt = {key: normalize_label(key) for key in gt_inputs.keys()}
    candidates: List[Tuple[str, str, str]] = []
    for var in predicted_variables:
        var_id = str(var.get("id") or "")
        var_name = normalize_label(var.get("name") or "")
        if not var_id:
            continue
        candidates.append((var_id, var_name, _slug_like(var_id)))

    for original_key, gt_name in normalized_gt.items():
        best_var_id = ""
        best_score = -1
        gt_slug = _slug_like(gt_name)
        for var_id, var_name, var_slug in candidates:
            score = 0
            if gt_name == var_name:
                score = 100
            elif gt_slug and gt_slug in var_slug:
                score = 90
            elif gt_name and gt_name in var_name:
                score = 80
            elif var_name and var_name in gt_name:
                score = 70
            elif gt_slug and var_slug and (gt_slug in var_name.replace(" ", "_") or var_slug in gt_slug):
                score = 60
            if score > best_score:
                best_score = score
                best_var_id = var_id
        if best_score >= 60 and best_var_id:
            mapping[original_key] = best_var_id

    return mapping


def _prepare_outputs_for_interpreter(
    analysis: Mapping[str, Any],
    flowchart: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    outputs = analysis.get("outputs")
    prepared: List[Dict[str, Any]] = []
    if isinstance(outputs, Sequence):
        for output in outputs:
            if isinstance(output, Mapping):
                name = str(output.get("name") or output.get("value") or "").strip()
            else:
                name = str(output).strip()
            if name:
                prepared.append({"name": name})
    if prepared:
        return prepared

    nodes = flowchart.get("nodes") if isinstance(flowchart, Mapping) else []
    if isinstance(nodes, Sequence):
        for node in nodes:
            if not isinstance(node, Mapping):
                continue
            if canonicalize_node_type(node.get("type")) == "end":
                label = str(node.get("label") or "").strip()
                if label:
                    prepared.append({"name": label})
    return prepared


def _semantic_score(
    analysis: Mapping[str, Any],
    flowchart: Mapping[str, Any],
    ground_truth_module: Any,
) -> Dict[str, Any]:
    test_cases = getattr(ground_truth_module, "TEST_CASES", None)
    if not isinstance(test_cases, list) or not test_cases:
        return {
            "score": 0.0,
            "matched": 0,
            "total": 0,
            "success_rate": 0.0,
            "execution_failures": 0,
            "mapping_coverage": 0.0,
            "errors": ["Ground truth module has no TEST_CASES."],
        }

    variables = analysis.get("variables") if isinstance(analysis.get("variables"), list) else []
    outputs = _prepare_outputs_for_interpreter(analysis, flowchart)

    tree = analysis.get("tree")
    if not isinstance(tree, Mapping) or not isinstance(tree.get("start"), Mapping):
        nodes = flowchart.get("nodes") if isinstance(flowchart, Mapping) else []
        edges = flowchart.get("edges") if isinstance(flowchart, Mapping) else []
        if isinstance(nodes, list) and isinstance(edges, list):
            tree = tree_from_flowchart(nodes, edges)

    if not isinstance(tree, Mapping) or "start" not in tree:
        return {
            "score": 0.0,
            "matched": 0,
            "total": len(test_cases),
            "success_rate": 0.0,
            "execution_failures": len(test_cases),
            "mapping_coverage": 0.0,
            "errors": ["Predicted analysis does not contain an executable tree."],
        }

    interpreter = TreeInterpreter(
        tree=dict(tree),
        variables=list(variables),
        outputs=list(outputs),
    )

    matched = 0
    execution_failures = 0
    mapped_inputs_total = 0
    gt_inputs_total = 0
    failure_samples: List[Dict[str, Any]] = []

    defaults = _infer_defaults_for_variables(variables)

    for idx, test_case in enumerate(test_cases):
        case_inputs = test_case.get("inputs") if isinstance(test_case, Mapping) else {}
        if not isinstance(case_inputs, Mapping):
            continue

        expected_output = test_case.get("expected_output")
        if expected_output is None:
            expected_output = ground_truth_module.determine_workflow_outcome(dict(case_inputs))

        input_map = _match_ground_truth_inputs_to_predicted_ids(case_inputs, variables)
        mapped_inputs_total += len(input_map)
        gt_inputs_total += len(case_inputs)

        runtime_inputs = dict(defaults)
        for gt_name, value in case_inputs.items():
            pred_id = input_map.get(gt_name)
            if pred_id:
                runtime_inputs[pred_id] = value

        result = interpreter.execute(runtime_inputs)
        if not result.success:
            execution_failures += 1
            if len(failure_samples) < 5:
                failure_samples.append(
                    {
                        "test_index": idx,
                        "error": result.error,
                        "expected": expected_output,
                    }
                )
            continue

        actual_norm = normalize_label(result.output)
        expected_norm = normalize_label(expected_output)
        if actual_norm == expected_norm:
            matched += 1
        elif len(failure_samples) < 5:
            failure_samples.append(
                {
                    "test_index": idx,
                    "predicted": result.output,
                    "expected": expected_output,
                }
            )

    total = len(test_cases)
    score = matched / total if total else 0.0
    mapping_coverage = mapped_inputs_total / gt_inputs_total if gt_inputs_total else 0.0

    return {
        "score": score,
        "matched": matched,
        "total": total,
        "success_rate": score,
        "execution_failures": execution_failures,
        "mapping_coverage": mapping_coverage,
        "failures": failure_samples,
    }


def score_trial(
    case_config: Mapping[str, Any],
    analysis: Mapping[str, Any],
    flowchart: Mapping[str, Any],
    ground_truth_module: Any,
) -> Dict[str, Any]:
    ref_nodes = case_config.get("canonical_expected_nodes") or []
    ref_edges = case_config.get("canonical_expected_edges") or []
    ref_variables = case_config.get("expected_variables") or []
    ref_outputs = case_config.get("expected_outputs") or []

    pred_nodes = flowchart.get("nodes") if isinstance(flowchart.get("nodes"), list) else []
    pred_edges = flowchart.get("edges") if isinstance(flowchart.get("edges"), list) else []
    pred_variables = analysis.get("variables") if isinstance(analysis.get("variables"), list) else []
    pred_outputs = analysis.get("outputs") if isinstance(analysis.get("outputs"), list) else []

    # Nodes
    pred_node_tokens = _node_tokens(pred_nodes)
    ref_node_tokens = _node_tokens(ref_nodes)
    node_prf = _compute_prf(
        matched=len(pred_node_tokens & ref_node_tokens),
        predicted_total=len(pred_node_tokens),
        reference_total=len(ref_node_tokens),
    )

    # Edges
    pred_id_to_label = {str(n.get("id")): str(n.get("label") or "") for n in pred_nodes if isinstance(n, Mapping)}
    ref_id_to_label = {str(n.get("id")): str(n.get("label") or "") for n in ref_nodes if isinstance(n, Mapping)}
    pred_edge_tokens = _edge_tokens(pred_edges, pred_id_to_label)
    ref_edge_tokens = _edge_tokens(ref_edges, ref_id_to_label)
    edge_prf = _compute_prf(
        matched=len(pred_edge_tokens & ref_edge_tokens),
        predicted_total=len(pred_edge_tokens),
        reference_total=len(ref_edge_tokens),
    )

    # Variables
    pred_var_tokens = _variable_tokens(pred_variables)
    ref_var_tokens = _variable_tokens(ref_variables)
    variable_prf = _compute_prf(
        matched=len(pred_var_tokens & ref_var_tokens),
        predicted_total=len(pred_var_tokens),
        reference_total=len(ref_var_tokens),
    )

    # Outputs
    pred_out_tokens = _output_tokens(pred_outputs)
    if not pred_out_tokens:
        pred_out_tokens = _output_tokens([n.get("label") for n in pred_nodes if canonicalize_node_type(n.get("type")) == "end"])
    ref_out_tokens = _output_tokens(ref_outputs)
    output_prf = _compute_prf(
        matched=len(pred_out_tokens & ref_out_tokens),
        predicted_total=len(pred_out_tokens),
        reference_total=len(ref_out_tokens),
    )

    # Semantic
    semantic = _semantic_score(analysis, flowchart, ground_truth_module)

    # Validity
    validator = WorkflowValidator()
    valid, validation_errors = validator.validate(
        {
            "nodes": pred_nodes,
            "edges": pred_edges,
            "variables": pred_variables,
        },
        strict=True,
    )
    validity_score = 1.0 if valid else 0.0

    metrics = {
        "node_f1": node_prf.f1,
        "edge_f1": edge_prf.f1,
        "variable_f1": variable_prf.f1,
        "output_f1": output_prf.f1,
        "semantic_score": float(semantic.get("score", 0.0)),
        "validity_score": validity_score,
    }

    composite_raw = 0.0
    for metric, weight in WEIGHTS.items():
        composite_raw += metrics[metric] * weight

    details = {
        "node": {
            "matched": node_prf.matched,
            "predicted_total": node_prf.predicted_total,
            "reference_total": node_prf.reference_total,
            "precision": node_prf.precision,
            "recall": node_prf.recall,
        },
        "edge": {
            "matched": edge_prf.matched,
            "predicted_total": edge_prf.predicted_total,
            "reference_total": edge_prf.reference_total,
            "precision": edge_prf.precision,
            "recall": edge_prf.recall,
        },
        "variable": {
            "matched": variable_prf.matched,
            "predicted_total": variable_prf.predicted_total,
            "reference_total": variable_prf.reference_total,
            "precision": variable_prf.precision,
            "recall": variable_prf.recall,
        },
        "output": {
            "matched": output_prf.matched,
            "predicted_total": output_prf.predicted_total,
            "reference_total": output_prf.reference_total,
            "precision": output_prf.precision,
            "recall": output_prf.recall,
        },
        "semantic": semantic,
        "validity": {
            "is_valid": valid,
            "error_count": len(validation_errors),
            "errors": [err.message for err in validation_errors[:10]],
        },
    }
    details.update(_node_detail_counts(pred_nodes, ref_nodes))
    details.update(_edge_detail_counts(pred_edges, ref_edges, pred_id_to_label, ref_id_to_label))

    percentage_metrics = {name: round(value * 100.0, 2) for name, value in metrics.items()}

    return {
        "metrics": metrics,
        "percentage_metrics": percentage_metrics,
        "composite_raw": composite_raw,
        "composite_score": round(composite_raw * 100.0, 2),
        "details": details,
    }
