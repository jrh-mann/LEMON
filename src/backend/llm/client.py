"""LLM client helpers."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("backend.llm")

from .anthropic import (
    _convert_openai_tools_to_anthropic,
    _parse_anthropic_response,
    _to_anthropic_messages,
)
from .env import get_anthropic_client, get_anthropic_model, load_env


def call_llm(
    messages: List[Dict[str, Any]],
    *,
    max_completion_tokens: int = 60000,
    response_format: Optional[Dict[str, Any]] = None,
) -> str:
    load_env()
    if response_format:
        logger.debug("response_format ignored for Anthropic")
    client = get_anthropic_client()
    system, converted = _to_anthropic_messages(messages)
    payload = {
        "model": get_anthropic_model(),
        "max_tokens": max_completion_tokens,
        "system": system,
        "messages": converted,
    }
    chunks: List[str] = []

    def on_delta(text: str) -> None:
        if text:
            chunks.append(text)

    start = time.perf_counter()
    with client.messages.stream(**payload) as stream:
        for event in stream:
            if getattr(event, "type", "") == "content_block_delta":
                delta = getattr(event, "delta", None)
                text = getattr(delta, "text", None)
                if text:
                    on_delta(text)
        message = stream.get_final_message()
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info("Anthropic streaming completed ms=%.1f messages=%d", elapsed_ms, len(messages))
    parsed_text, _ = _parse_anthropic_response(message)
    text = "".join(chunks) if chunks else parsed_text
    if not text:
        raise RuntimeError("Anthropic returned empty content.")
    return text


def call_llm_with_tools(
    messages: List[Dict[str, Any]],
    *,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    max_completion_tokens: int = 60000,
    on_delta: Optional[Callable[[str], None]] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    load_env()
    if tool_choice is None and tools:
        tool_choice = "auto"
    client = get_anthropic_client()
    system, converted = _to_anthropic_messages(messages)
    tool_payload = [] if tool_choice == "none" else _convert_openai_tools_to_anthropic(tools)
    payload: Dict[str, Any] = {
        "model": get_anthropic_model(),
        "max_tokens": max_completion_tokens,
        "system": system,
        "messages": converted,
        "tools": tool_payload,
    }
    if tool_choice:
        if tool_choice == "none":
            payload["tool_choice"] = {"type": "none"}
        elif tool_choice == "any":
            payload["tool_choice"] = {"type": "any"}
        elif tool_choice == "auto":
            payload["tool_choice"] = {"type": "auto"}
        else:
            payload["tool_choice"] = {"type": "tool", "name": tool_choice}
    chunks: List[str] = []
    tool_blocks: Dict[int, Dict[str, Any]] = {}

    def handle_delta(text: str) -> None:
        if text:
            chunks.append(text)
        if on_delta:
            on_delta(text)

    def _call_stream() -> Any:
        with client.messages.stream(**payload) as stream:
            for event in stream:
                event_type = getattr(event, "type", "")
                if event_type == "content_block_start":
                    block = getattr(event, "content_block", None)
                    block_type = getattr(block, "type", None)
                    if block_type == "tool_use":
                        idx = getattr(event, "index", None)
                        if idx is None:
                            idx = getattr(event, "content_block_index", None)
                        tool_blocks[int(idx or 0)] = {
                            "id": getattr(block, "id", None),
                            "name": getattr(block, "name", None),
                            "input": getattr(block, "input", None),
                            "buffer": "",
                        }
                elif event_type == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    if delta:
                        text = getattr(delta, "text", None)
                        if text:
                            handle_delta(text)
                        delta_type = getattr(delta, "type", None)
                        if delta_type == "input_json_delta":
                            idx = getattr(event, "index", None)
                            if idx is None:
                                idx = getattr(event, "content_block_index", None)
                            block = tool_blocks.get(int(idx or 0))
                            if block is not None:
                                partial = getattr(delta, "partial_json", None)
                                if partial:
                                    block["buffer"] += partial
                elif event_type == "content_block_stop":
                    idx = getattr(event, "index", None)
                    if idx is None:
                        idx = getattr(event, "content_block_index", None)
                    block = tool_blocks.get(int(idx or 0))
                    if block is not None and block.get("buffer"):
                        try:
                            block["input"] = json.loads(block["buffer"])
                        except json.JSONDecodeError:
                            pass
            return stream.get_final_message()

    start = time.perf_counter()
    message = _call_stream()
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info("Anthropic streaming completed ms=%.1f messages=%d", elapsed_ms, len(messages))
    parsed_text, tool_calls = _parse_anthropic_response(message)
    if not tool_calls:
        # Fallback: recover tool calls from stream events if final message omits them.
        recovered: List[Dict[str, Any]] = []
        for block in tool_blocks.values():
            name = block.get("name")
            tool_id = block.get("id")
            tool_input = block.get("input") or {}
            try:
                args_text = json.dumps(tool_input, ensure_ascii=True)
            except (TypeError, ValueError):
                args_text = "{}"
            if name:
                recovered.append(
                    {
                        "id": tool_id,
                        "type": "function",
                        "function": {"name": name, "arguments": args_text},
                    }
                )
        if recovered:
            tool_calls = recovered
    text = "".join(chunks) if chunks else parsed_text
    return text, tool_calls


def call_llm_stream(
    messages: List[Dict[str, Any]],
    *,
    max_completion_tokens: int = 60000,
    response_format: Optional[Dict[str, Any]] = None,
    on_delta: Callable[[str], None],
) -> str:
    load_env()
    if response_format:
        logger.debug("response_format ignored for Anthropic")
    client = get_anthropic_client()
    system, converted = _to_anthropic_messages(messages)
    payload = {
        "model": get_anthropic_model(),
        "max_tokens": max_completion_tokens,
        "system": system,
        "messages": converted,
    }
    start = time.perf_counter()
    with client.messages.stream(**payload) as stream:
        for event in stream:
            if getattr(event, "type", "") == "content_block_delta":
                delta = getattr(event, "delta", None)
                text = getattr(delta, "text", None)
                if text:
                    on_delta(text)
        message = stream.get_final_message()
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info("Anthropic streaming completed ms=%.1f messages=%d", elapsed_ms, len(messages))
    text, _ = _parse_anthropic_response(message)
    return text
