"""Helpers for detecting recursive subflow references."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Set


def detect_subflow_cycles(
    nodes: List[Dict[str, Any]],
    fetch_subworkflow: Callable[[str], Any] | None,
) -> List[str]:
    """Return unique recursive subflow cycle paths reachable from nodes."""
    if fetch_subworkflow is None:
        return []

    seen_cycles: Set[str] = set()
    warnings: List[str] = []
    visited_workflows: Set[str] = set()

    def walk(current_nodes: List[Dict[str, Any]], stack: List[str]) -> None:
        for node in current_nodes:
            if node.get("type") != "subprocess":
                continue

            subworkflow_id = node.get("subworkflow_id")
            if not isinstance(subworkflow_id, str) or not subworkflow_id:
                continue

            if subworkflow_id in stack:
                cycle_path = stack[stack.index(subworkflow_id) :] + [subworkflow_id]
                cycle_text = " -> ".join(cycle_path)
                if cycle_text not in seen_cycles:
                    seen_cycles.add(cycle_text)
                    warnings.append(
                        f"Recursive subflow cycle detected: {cycle_text}. "
                        "Export can continue, but executing the exported artifact may fail if this cycle is reached."
                    )
                continue

            if subworkflow_id in visited_workflows:
                continue

            subworkflow = fetch_subworkflow(subworkflow_id)
            if subworkflow is None:
                continue

            visited_workflows.add(subworkflow_id)
            walk(getattr(subworkflow, "nodes", []), stack + [subworkflow_id])

    walk(nodes, [])
    return warnings
