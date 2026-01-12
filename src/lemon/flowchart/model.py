"""Flowchart schema and normalization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

ALLOWED_TYPES = {"start", "process", "decision", "subprocess", "end"}
ALLOWED_COLORS = {"teal", "amber", "green", "slate", "rose", "sky"}


def _coerce_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _unique_id(prefix: str, used: set[str]) -> str:
    idx = 1
    base = prefix or "node"
    candidate = f"{base}_{idx}"
    while candidate in used:
        idx += 1
        candidate = f"{base}_{idx}"
    used.add(candidate)
    return candidate


@dataclass
class FlowNode:
    id: str
    type: str
    label: str
    x: Optional[float] = None
    y: Optional[float] = None
    color: str = "teal"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "x": self.x,
            "y": self.y,
            "color": self.color,
        }


@dataclass
class FlowEdge:
    from_id: str
    to_id: str
    label: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"from": self.from_id, "to": self.to_id, "label": self.label}


@dataclass
class Flowchart:
    nodes: List[FlowNode] = field(default_factory=list)
    edges: List[FlowEdge] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Flowchart":
        nodes_raw = data.get("nodes") or []
        edges_raw = data.get("edges") or []

        nodes: List[FlowNode] = []
        used_ids: set[str] = set()

        for idx, node in enumerate(nodes_raw):
            if not isinstance(node, dict):
                continue
            raw_id = str(node.get("id") or f"n{idx + 1}")
            node_id = raw_id
            if node_id in used_ids:
                node_id = _unique_id(raw_id, used_ids)
            else:
                used_ids.add(node_id)

            node_type = str(node.get("type") or "process").lower()
            if node_type not in ALLOWED_TYPES:
                node_type = "process"

            color = str(node.get("color") or "teal").lower()
            if color not in ALLOWED_COLORS:
                color = "teal"

            label = str(node.get("label") or "Step")
            x = _coerce_float(node.get("x"))
            y = _coerce_float(node.get("y"))

            nodes.append(
                FlowNode(id=node_id, type=node_type, label=label, x=x, y=y, color=color)
            )

        node_ids = {node.id for node in nodes}
        edges: List[FlowEdge] = []
        for edge in edges_raw:
            if not isinstance(edge, dict):
                continue
            source = edge.get("from") or edge.get("source")
            target = edge.get("to") or edge.get("target")
            if not source or not target:
                continue
            if source not in node_ids or target not in node_ids:
                continue
            label = str(edge.get("label") or "")
            edges.append(FlowEdge(from_id=str(source), to_id=str(target), label=label))

        return cls(nodes=nodes, edges=edges)
