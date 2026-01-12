"""Flowchart construction from analysis models."""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from ..core.workflow import WorkflowAnalysis
from .model import Flowchart, FlowEdge, FlowNode


def flowchart_from_analysis(analysis: WorkflowAnalysis) -> Flowchart:
    nodes: List[FlowNode] = []
    edges: List[FlowEdge] = []
    used_ids: set[str] = set()
    name_map: Dict[str, str] = {}

    def add_node(label: str, node_type: str, color: str) -> str:
        node_id = _unique_node_id(_normalize_key(label) or node_type, used_ids)
        nodes.append(
            FlowNode(id=node_id, type=node_type, label=label, color=color, x=None, y=None)
        )
        key = _normalize_key(label)
        if key and key not in name_map:
            name_map[key] = node_id
        return node_id

    start_id = add_node("Start", "start", "teal")

    for decision in analysis.decision_points:
        label = decision.name or decision.description or "Decision"
        node_id = add_node(label, "decision", "amber")
        name_map[_normalize_key(decision.name or label)] = node_id

    for output in analysis.outputs:
        label = output.name or "Output"
        node_id = add_node(label, "end", "green")
        name_map[_normalize_key(output.name or label)] = node_id

    for decision in analysis.decision_points:
        source_id = _find_node_id(name_map, decision.name)
        if not source_id:
            continue
        for branch in decision.branches:
            target_label = branch.leads_to or branch.outcome or ""
            target_id = _find_node_id(name_map, target_label)
            if not target_id and target_label:
                target_id = add_node(target_label, "process", "slate")
            if not target_id:
                continue
            label = branch.condition or branch.outcome or ""
            if not _edge_exists(edges, source_id, target_id, label):
                edges.append(FlowEdge(from_id=source_id, to_id=target_id, label=label))

    if analysis.workflow_paths:
        for path in analysis.workflow_paths:
            decisions = []
            for item in path.decision_sequence:
                if "->" in item:
                    name = item.split("->", 1)[0].strip()
                else:
                    name = item.strip()
                if name:
                    decisions.append(name)
            for idx, name in enumerate(decisions):
                source_id = _find_node_id(name_map, name)
                if not source_id:
                    continue
                if idx + 1 < len(decisions):
                    target_id = _find_node_id(name_map, decisions[idx + 1])
                    if target_id and not _edge_exists(edges, source_id, target_id, ""):
                        edges.append(FlowEdge(from_id=source_id, to_id=target_id, label=""))
                else:
                    output_id = _find_node_id(name_map, path.output)
                    if output_id and not _edge_exists(edges, source_id, output_id, ""):
                        edges.append(FlowEdge(from_id=source_id, to_id=output_id, label=""))

    incoming: Dict[str, int] = {node.id: 0 for node in nodes}
    for edge in edges:
        incoming[edge.to_id] = incoming.get(edge.to_id, 0) + 1

    for node_id, count in incoming.items():
        if node_id == start_id:
            continue
        if count == 0:
            edges.append(FlowEdge(from_id=start_id, to_id=node_id, label=""))

    return Flowchart(nodes=nodes, edges=edges)


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _unique_node_id(prefix: str, used: set[str]) -> str:
    idx = 1
    node_id = f"{prefix}_{idx}"
    while node_id in used:
        idx += 1
        node_id = f"{prefix}_{idx}"
    used.add(node_id)
    return node_id


def _find_node_id(name_map: Dict[str, str], value: Optional[str]) -> Optional[str]:
    key = _normalize_key(value or "")
    if not key:
        return None
    if key in name_map:
        return name_map[key]
    for stored_key, node_id in name_map.items():
        if key in stored_key or stored_key in key:
            return node_id
    return None


def _edge_exists(edges: List[FlowEdge], source: str, target: str, label: str) -> bool:
    for edge in edges:
        if edge.from_id == source and edge.to_id == target:
            if not label or edge.label == label:
                return True
    return False
