"""Flowchart conversion helpers."""

from __future__ import annotations

from typing import Any, Dict, List


def _map_node_type(raw_type: str) -> str:
    mapped = {
        "action": "process",
    }
    return mapped.get(raw_type, raw_type)


def flowchart_from_tree(tree: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    if not tree:
        return {"nodes": [], "edges": []}

    start = tree.get("start")
    if not isinstance(start, dict):
        return {"nodes": [], "edges": []}

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    seen = set()
    stack = [start]

    while stack:
        node = stack.pop()
        node_id = node.get("id")
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)

        raw_type = str(node.get("type") or "process")
        node_type = _map_node_type(raw_type)
        nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "label": node.get("label") or node_id,
                # Top-left coordinates; frontend auto-layout will adjust.
                "x": 0,
                "y": 0,
            }
        )

        for child in node.get("children") or []:
            child_id = child.get("id")
            if not child_id:
                continue
            edges.append(
                {
                    "id": f"{node_id}->{child_id}",
                    "from": node_id,
                    "to": child_id,
                    "label": child.get("edge_label") or "",
                }
            )
            stack.append(child)

    return {"nodes": nodes, "edges": edges}
