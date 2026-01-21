"""Shared helpers for workflow edit tools."""

from __future__ import annotations

from typing import Any, Dict, Optional

NODE_COLOR_BY_TYPE = {
    "start": "teal",
    "decision": "amber",
    "end": "green",
    "subprocess": "rose",
    "process": "slate",
}


def get_node_color(node_type: str) -> str:
    return NODE_COLOR_BY_TYPE.get(node_type, "slate")


def input_ref_error(input_ref: Optional[str], session_state: Dict[str, Any]) -> Optional[str]:
    if not input_ref:
        return None
    workflow_analysis = session_state.get("workflow_analysis", {})
    inputs = workflow_analysis.get("inputs", [])
    normalized_ref = input_ref.strip().lower()
    input_exists = any(
        inp.get("name", "").strip().lower() == normalized_ref
        for inp in inputs
    )
    if input_exists:
        return None
    return f"Input '{input_ref}' not found. Register it first with add_workflow_input."

