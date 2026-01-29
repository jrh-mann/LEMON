"""Analysis normalization helpers."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set


def slugify_input_name(name: str) -> str:
    text = name.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def deterministic_input_id(name: str, input_type: str) -> str:
    base = slugify_input_name(name) or "input"
    return f"input_{base}_{input_type}"


def normalize_analysis(analysis: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(analysis, dict):
        return analysis

    inputs = analysis.get("inputs")
    if not isinstance(inputs, list):
        inputs = []

    normalized: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    duplicates: List[str] = []

    for raw in inputs:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        input_type = str(raw.get("type") or "").strip()
        if not name or not input_type:
            continue
        key = f"{slugify_input_name(name)}:{input_type}"
        if key in seen:
            duplicates.append(name)
            continue
        seen.add(key)
        item = dict(raw)
        item["name"] = name
        item["type"] = input_type
        item["id"] = deterministic_input_id(name, input_type)
        normalized.append(item)

    analysis["inputs"] = normalized

    if duplicates:
        doubts = analysis.get("doubts")
        if not isinstance(doubts, list):
            doubts = []
        for name in duplicates:
            doubts.append(f"Duplicate input removed: {name}")
        analysis["doubts"] = doubts

    _normalize_input_ids(analysis, {item["id"] for item in normalized})
    return analysis


def _normalize_input_ids(analysis: Dict[str, Any], valid_ids: Set[str]) -> None:
    """Normalize input_ids on tree nodes to only contain valid input IDs."""
    tree = analysis.get("tree")
    if not isinstance(tree, dict):
        return
    start = tree.get("start")
    if not isinstance(start, dict):
        return

    def walk(node: Dict[str, Any]) -> None:
        input_ids = node.get("input_ids")
        if isinstance(input_ids, str):
            input_ids = [input_ids]
        if isinstance(input_ids, list):
            node["input_ids"] = [i for i in input_ids if isinstance(i, str) and i in valid_ids]
        elif input_ids is not None:
            node["input_ids"] = []

        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child)

    walk(start)
