"""Response helpers for API and socket handlers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def extract_tool_calls(
    response_text: str, *, include_result: bool = True
) -> List[Dict[str, Any]]:
    """Extract tool calls from a response. Returns empty list (tools are tracked elsewhere)."""
    return []


def extract_flowchart(response_text: str) -> Optional[Dict[str, Any]]:
    """Extract flowchart from response text. Returns None (flowcharts built incrementally)."""
    return None


def summarize_response(response_text: str) -> str:
    """Summarize response text. Returns it unchanged."""
    return response_text


def emit_stream_chunks(text: str, emit: Any, *, chunk_size: int = 1000) -> None:
    if not text:
        return
    for idx in range(0, len(text), chunk_size):
        emit("chat_stream", {"chunk": text[idx : idx + chunk_size]})
