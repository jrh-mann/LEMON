"""Analysis normalization helpers."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple


def slugify_input_name(name: str) -> str:
    text = name.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def deterministic_input_id(name: str, input_type: str) -> str:
    base = slugify_input_name(name) or "input"
    return f"input_{base}_{input_type}"


def normalize_analysis(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize analysis data, ensuring variables have IDs and are deduplicated.
    
    Reads from 'inputs' and tree condition/input references, then writes to
    'variables' key (unified format).
    """
    if not isinstance(analysis, dict):
        return analysis

    # Read from 'inputs' (AI response format) 
    inputs = analysis.get("inputs")
    if not isinstance(inputs, list):
        inputs = []

    normalized: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    duplicates: List[str] = []
    seen_ids: Set[str] = set()

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
        input_id = str(raw.get("id") or deterministic_input_id(name, input_type)).strip()
        if input_id in seen_ids:
            duplicates.append(name)
            continue
        seen.add(key)
        seen_ids.add(input_id)
        item = dict(raw)
        item["name"] = name
        item["type"] = input_type
        item["id"] = input_id
        item["source"] = "input"  # Mark as user input variable
        normalized.append(item)

    # Backfill inputs from node condition/input references when model leaves
    # top-level inputs empty.
    for inferred in _infer_inputs_from_tree(analysis.get("tree")):
        name = str(inferred.get("name") or "").strip()
        input_type = str(inferred.get("type") or "").strip()
        input_id = str(inferred.get("id") or "").strip()
        if not name or not input_type or not input_id:
            continue
        key = f"{slugify_input_name(name)}:{input_type}"
        if key in seen or input_id in seen_ids:
            continue
        seen.add(key)
        seen_ids.add(input_id)
        normalized.append(inferred)

    # Write to 'variables' (unified format)
    analysis["variables"] = normalized
    # Remove old 'inputs' key to avoid confusion
    if "inputs" in analysis:
        del analysis["inputs"]

    if duplicates:
        doubts = analysis.get("doubts")
        if not isinstance(doubts, list):
            doubts = []
        for name in duplicates:
            doubts.append(f"Duplicate input removed: {name}")
        analysis["doubts"] = doubts

    _hydrate_input_ids_from_conditions(analysis)
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


_INPUT_TYPES = ("int", "float", "bool", "string", "enum", "date")


def _parse_input_id(input_id: str) -> Tuple[str, str] | None:
    if not isinstance(input_id, str):
        return None
    text = input_id.strip()
    if not text.startswith("input_"):
        return None

    for input_type in _INPUT_TYPES:
        suffix = f"_{input_type}"
        if text.endswith(suffix):
            name = text[len("input_") : -len(suffix)].strip("_")
            if name:
                return name, input_type
    return None


def _guess_input_type_from_condition(condition: Dict[str, Any]) -> Optional[str]:
    comparator = str(condition.get("comparator") or "").strip().lower()
    if comparator in {"is_true", "is_false"}:
        return "bool"
    if comparator in {"enum_eq", "enum_neq"}:
        return "enum"
    if comparator.startswith("str_"):
        return "string"
    if comparator.startswith("date_"):
        return "date"
    if comparator in {"eq", "neq", "lt", "lte", "gt", "gte", "within_range"}:
        return "float"
    return None


def _infer_inputs_from_tree(tree: Any) -> List[Dict[str, Any]]:
    if not isinstance(tree, dict):
        return []
    start = tree.get("start")
    if not isinstance(start, dict):
        return []

    refs: List[Tuple[str, Optional[str]]] = []

    def walk(node: Dict[str, Any]) -> None:
        condition = node.get("condition")
        if isinstance(condition, dict):
            input_id = condition.get("input_id")
            if isinstance(input_id, str) and input_id.strip():
                refs.append((input_id.strip(), _guess_input_type_from_condition(condition)))

        input_ids = node.get("input_ids")
        if isinstance(input_ids, str):
            input_ids = [input_ids]
        if isinstance(input_ids, list):
            for input_id in input_ids:
                if isinstance(input_id, str) and input_id.strip():
                    refs.append((input_id.strip(), None))

        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child)

    walk(start)

    inferred: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for input_id, hint_type in refs:
        if input_id in seen:
            continue
        seen.add(input_id)

        parsed = _parse_input_id(input_id)
        if parsed:
            name, input_type = parsed
            normalized_id = input_id
        else:
            input_type = hint_type or "string"
            if input_id.startswith("input_"):
                raw_name = input_id[len("input_") :]
            else:
                raw_name = input_id
            suffix = f"_{input_type}"
            name = raw_name[: -len(suffix)] if raw_name.endswith(suffix) else raw_name
            name = slugify_input_name(name) or "input"
            normalized_id = deterministic_input_id(name, input_type)

        inferred.append(
            {
                "id": normalized_id,
                "name": name,
                "type": input_type,
                "description": "Inferred from workflow conditions.",
                "source": "inferred",
            }
        )
    return inferred


def _hydrate_input_ids_from_conditions(analysis: Dict[str, Any]) -> None:
    tree = analysis.get("tree")
    if not isinstance(tree, dict):
        return
    start = tree.get("start")
    if not isinstance(start, dict):
        return

    def walk(node: Dict[str, Any]) -> None:
        raw_input_ids = node.get("input_ids")
        if isinstance(raw_input_ids, str):
            input_ids: List[str] = [raw_input_ids]
        elif isinstance(raw_input_ids, list):
            input_ids = [item for item in raw_input_ids if isinstance(item, str)]
        else:
            input_ids = []

        condition = node.get("condition")
        if isinstance(condition, dict):
            condition_input_id = condition.get("input_id")
            if isinstance(condition_input_id, str) and condition_input_id.strip():
                cid = condition_input_id.strip()
                if cid not in input_ids:
                    input_ids.append(cid)

        if input_ids:
            node["input_ids"] = input_ids
        elif "input_ids" in node:
            node["input_ids"] = []

        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child)

    walk(start)
