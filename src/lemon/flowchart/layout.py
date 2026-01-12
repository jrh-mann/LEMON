"""Flowchart layout and crossing detection."""

from __future__ import annotations

from typing import Dict, List, Tuple

from .model import Flowchart


def _build_index(flowchart: Flowchart) -> Dict[str, int]:
    return {node.id: idx for idx, node in enumerate(flowchart.nodes)}


def _parents(flowchart: Flowchart) -> Dict[str, List[str]]:
    parents: Dict[str, List[str]] = {node.id: [] for node in flowchart.nodes}
    for edge in flowchart.edges:
        parents.setdefault(edge.to_id, []).append(edge.from_id)
    return parents


def _children(flowchart: Flowchart) -> Dict[str, List[str]]:
    children: Dict[str, List[str]] = {node.id: [] for node in flowchart.nodes}
    for edge in flowchart.edges:
        children.setdefault(edge.from_id, []).append(edge.to_id)
    return children


def assign_levels(flowchart: Flowchart) -> Dict[str, int]:
    levels = {node.id: 0 for node in flowchart.nodes}
    max_iters = max(1, len(flowchart.nodes))
    for _ in range(max_iters):
        changed = False
        for edge in flowchart.edges:
            src_level = levels.get(edge.from_id, 0)
            next_level = src_level + 1
            if next_level > levels.get(edge.to_id, 0):
                levels[edge.to_id] = next_level
                changed = True
        if not changed:
            break
    return levels


def order_levels(flowchart: Flowchart, levels: Dict[str, int]) -> Dict[int, List[str]]:
    level_map: Dict[int, List[str]] = {}
    for node_id, level in levels.items():
        level_map.setdefault(level, []).append(node_id)

    parents = _parents(flowchart)
    children = _children(flowchart)

    order_index: Dict[str, int] = {}
    for level, nodes in level_map.items():
        nodes.sort()
        for idx, node_id in enumerate(nodes):
            order_index[node_id] = idx

    max_level = max(level_map) if level_map else 0
    for _ in range(4):
        for level in range(1, max_level + 1):
            nodes = level_map.get(level, [])
            nodes.sort(
                key=lambda node_id: _avg_index(order_index, parents.get(node_id, []))
            )
            for idx, node_id in enumerate(nodes):
                order_index[node_id] = idx
        for level in range(max_level - 1, -1, -1):
            nodes = level_map.get(level, [])
            nodes.sort(
                key=lambda node_id: _avg_index(order_index, children.get(node_id, []))
            )
            for idx, node_id in enumerate(nodes):
                order_index[node_id] = idx

    return level_map


def _avg_index(order_index: Dict[str, int], related: List[str]) -> float:
    if not related:
        return 0.0
    return sum(order_index.get(node_id, 0) for node_id in related) / len(related)


def layout_flowchart(
    flowchart: Flowchart,
    *,
    spacing_x: int = 240,
    spacing_y: int = 150,
    padding_x: int = 120,
    padding_y: int = 120,
) -> Flowchart:
    if not flowchart.nodes:
        return flowchart

    levels = assign_levels(flowchart)
    level_map = order_levels(flowchart, levels)

    max_level = max(level_map) if level_map else 0
    max_group = max((len(nodes) for nodes in level_map.values()), default=1)
    width = max(1200, padding_x * 2 + (max_group - 1) * spacing_x)
    height = max(800, padding_y * 2 + max_level * spacing_y)

    node_lookup = {node.id: node for node in flowchart.nodes}
    for level, node_ids in level_map.items():
        group_width = (len(node_ids) - 1) * spacing_x
        start_x = max(padding_x, (width - group_width) / 2)
        y = padding_y + level * spacing_y
        for idx, node_id in enumerate(node_ids):
            node = node_lookup[node_id]
            node.x = start_x + idx * spacing_x
            node.y = y

    return flowchart


def count_edge_crossings(flowchart: Flowchart) -> int:
    segments = _edge_segments(flowchart)
    crossings = 0
    for i in range(len(segments)):
        a1, a2 = segments[i]
        for j in range(i + 1, len(segments)):
            b1, b2 = segments[j]
            if _segments_cross(a1, a2, b1, b2):
                crossings += 1
    return crossings


def _edge_segments(flowchart: Flowchart) -> List[Tuple[Tuple[float, float], Tuple[float, float]]]:
    node_map = {node.id: node for node in flowchart.nodes}
    segments = []
    for edge in flowchart.edges:
        src = node_map.get(edge.from_id)
        dst = node_map.get(edge.to_id)
        if not src or not dst:
            continue
        if src.x is None or src.y is None or dst.x is None or dst.y is None:
            continue
        segments.append(((src.x, src.y), (dst.x, dst.y)))
    return segments


def _segments_cross(
    a1: Tuple[float, float],
    a2: Tuple[float, float],
    b1: Tuple[float, float],
    b2: Tuple[float, float],
) -> bool:
    if a1 == b1 or a1 == b2 or a2 == b1 or a2 == b2:
        return False
    return _ccw(a1, b1, b2) != _ccw(a2, b1, b2) and _ccw(a1, a2, b1) != _ccw(a1, a2, b2)


def _ccw(a: Tuple[float, float], b: Tuple[float, float], c: Tuple[float, float]) -> bool:
    return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])
