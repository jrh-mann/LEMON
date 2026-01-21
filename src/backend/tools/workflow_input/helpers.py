"""Helpers for workflow input tools."""

from __future__ import annotations

from typing import Any, Dict


def ensure_workflow_analysis(session_state: Dict[str, Any]) -> Dict[str, Any]:
    if "workflow_analysis" not in session_state:
        session_state["workflow_analysis"] = {"inputs": [], "outputs": []}
    workflow_analysis = session_state["workflow_analysis"]
    if "inputs" not in workflow_analysis:
        workflow_analysis["inputs"] = []
    if "outputs" not in workflow_analysis:
        workflow_analysis["outputs"] = []
    return workflow_analysis


def normalize_input_name(name: str) -> str:
    return name.strip().lower()
