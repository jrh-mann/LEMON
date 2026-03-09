"""Helpers for updating and validating workflow variable references."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Tuple


def find_variable_references(nodes: List[Dict[str, Any]], variable_id: str) -> List[Dict[str, str]]:
    """Return all node references to a variable ID."""
    references: List[Dict[str, str]] = []
    for node in nodes:
        node_id = str(node.get("id", "unknown"))
        node_label = str(node.get("label", node_id))
        condition = node.get("condition")
        if isinstance(condition, dict):
            if "operator" in condition:
                for sub in condition.get("conditions", []):
                    if isinstance(sub, dict) and sub.get("input_id") == variable_id:
                        references.append({"node_id": node_id, "node_label": node_label, "field": "condition"})
                        break
            elif condition.get("input_id") == variable_id:
                references.append({"node_id": node_id, "node_label": node_label, "field": "condition"})

        calculation = node.get("calculation")
        if isinstance(calculation, dict):
            for operand in calculation.get("operands", []):
                if isinstance(operand, dict) and operand.get("kind") == "variable" and operand.get("ref") == variable_id:
                    references.append({"node_id": node_id, "node_label": node_label, "field": "calculation.operands"})
                    break

        if node.get("output_variable") == variable_id:
            references.append({"node_id": node_id, "node_label": node_label, "field": "output_variable"})

    return references


def rewrite_variable_references(
    nodes: List[Dict[str, Any]],
    *,
    old_variable_id: str,
    new_variable_id: str,
) -> Tuple[List[Dict[str, Any]], int]:
    """Rewrite all node references from one variable ID to another."""
    rewritten_nodes = deepcopy(nodes)
    rewrite_count = 0
    for node in rewritten_nodes:
        condition = node.get("condition")
        if isinstance(condition, dict):
            if "operator" in condition:
                for sub in condition.get("conditions", []):
                    if isinstance(sub, dict) and sub.get("input_id") == old_variable_id:
                        sub["input_id"] = new_variable_id
                        rewrite_count += 1
            elif condition.get("input_id") == old_variable_id:
                condition["input_id"] = new_variable_id
                rewrite_count += 1

        calculation = node.get("calculation")
        if isinstance(calculation, dict):
            for operand in calculation.get("operands", []):
                if isinstance(operand, dict) and operand.get("kind") == "variable" and operand.get("ref") == old_variable_id:
                    operand["ref"] = new_variable_id
                    rewrite_count += 1

        if node.get("output_variable") == old_variable_id:
            node["output_variable"] = new_variable_id
            rewrite_count += 1

    return rewritten_nodes, rewrite_count
