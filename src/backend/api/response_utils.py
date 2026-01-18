"""Response helpers for API and socket handlers."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def extract_tool_calls(
    response_text: str, *, include_result: bool = True
) -> List[Dict[str, Any]]:
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict) and payload.get("source") == "subagent":
        tool = payload.get("tool") or "unknown"
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        result = data if include_result else {"session_id": data.get("session_id")}
        return [{"tool": tool, "arguments": {}, "result": result}]
    return []


def extract_flowchart(response_text: str) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("source") != "subagent":
        return None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    flowchart = data.get("flowchart")
    if isinstance(flowchart, dict) and flowchart.get("nodes") is not None:
        return flowchart
    analysis = data.get("analysis") if isinstance(data.get("analysis"), dict) else {}
    flowchart = analysis.get("flowchart")
    if isinstance(flowchart, dict) and flowchart.get("nodes") is not None:
        return flowchart
    return None


def summarize_response(response_text: str) -> str:
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        return response_text
    if not isinstance(payload, dict) or payload.get("source") != "subagent":
        return response_text
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    analysis = data.get("analysis") if isinstance(data.get("analysis"), dict) else {}
    inputs = analysis.get("inputs") if isinstance(analysis.get("inputs"), list) else []
    outputs = analysis.get("outputs") if isinstance(analysis.get("outputs"), list) else []
    doubts = analysis.get("doubts") if isinstance(analysis.get("doubts"), list) else []

    def _fmt_items(items: list, key: str) -> str:
        lines = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get(key) or ""
            typ = item.get("type")
            if typ:
                lines.append(f"- {name} ({typ})")
            else:
                lines.append(f"- {name}")
        return "\n".join(lines) if lines else "- None"

    inputs_text = _fmt_items(inputs, "input")
    outputs_text = _fmt_items(outputs, "output")
    doubts_text = "\n".join(f"- {d}" for d in doubts) if doubts else "- None"

    return (
        "Analysis complete.\n\n"
        "Inputs:\n"
        f"{inputs_text}\n\n"
        "Outputs:\n"
        f"{outputs_text}\n\n"
        "Doubts:\n"
        f"{doubts_text}"
    )


def emit_stream_chunks(text: str, emit: Any, *, chunk_size: int = 1000) -> None:
    if not text:
        return
    for idx in range(0, len(text), chunk_size):
        emit("chat_stream", {"chunk": text[idx : idx + chunk_size]})
