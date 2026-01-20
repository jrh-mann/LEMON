"""LLM client helpers."""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("backend.llm")

from .anthropic import (
    _convert_openai_tools_to_anthropic,
    _parse_anthropic_response,
    _to_anthropic_messages,
)
from .env import get_anthropic_client, get_anthropic_model, load_env
from ..utils.tokens import record_token_usage


def _extract_usage(message: Any) -> Dict[str, Any]:
    usage = getattr(message, "usage", None)
    if usage is None and isinstance(message, dict):
        usage = message.get("usage")
    if usage is None:
        return {}

    def _get(field: str) -> Optional[int]:
        if isinstance(usage, dict):
            value = usage.get(field)
        else:
            value = getattr(usage, field, None)
        return int(value) if isinstance(value, int) else None

    input_tokens = _get("input_tokens")
    output_tokens = _get("output_tokens")
    cache_creation_tokens = _get("cache_creation_input_tokens")
    cache_read_tokens = _get("cache_read_input_tokens")
    total_tokens = None
    if input_tokens is not None or output_tokens is not None:
        total_tokens = (input_tokens or 0) + (output_tokens or 0)

    payload: Dict[str, Any] = {}
    if input_tokens is not None:
        payload["input_tokens"] = input_tokens
    if output_tokens is not None:
        payload["output_tokens"] = output_tokens
    if total_tokens is not None:
        payload["total_tokens"] = total_tokens
    if cache_creation_tokens is not None:
        payload["cache_creation_input_tokens"] = cache_creation_tokens
    if cache_read_tokens is not None:
        payload["cache_read_input_tokens"] = cache_read_tokens
    return payload


def _record_tokens(
    *,
    request_id: str,
    message: Any,
    model: str,
    caller: Optional[str],
    request_tag: Optional[str],
    function_name: str,
    tool_choice: Optional[str],
    tool_count: int,
    message_count: int,
    elapsed_ms: float,
    tool_names: Optional[List[str]] = None,
) -> None:
    provider_id = getattr(message, "id", None)
    if provider_id is None and isinstance(message, dict):
        provider_id = message.get("id")
    entry = {
        "request_id": request_id,
        "provider_message_id": provider_id,
        "model": model,
        "caller": caller or "unknown",
        "request_tag": request_tag or "",
        "function": function_name,
        "streaming": True,
        "tool_choice": tool_choice or "",
        "tool_count": tool_count,
        "tools": tool_names or [],
        "message_count": message_count,
        "elapsed_ms": round(elapsed_ms, 2),
        "usage": _extract_usage(message),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        record_token_usage(entry)
    except Exception as exc:
        logger.warning("Failed to record token usage: %s", exc)


def call_llm(
    messages: List[Dict[str, Any]],
    *,
    max_completion_tokens: int = 60000,
    response_format: Optional[Dict[str, Any]] = None,
    caller: Optional[str] = None,
    request_tag: Optional[str] = None,
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
    request_id = uuid.uuid4().hex
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
    _record_tokens(
        request_id=request_id,
        message=message,
        model=payload["model"],
        caller=caller,
        request_tag=request_tag,
        function_name="call_llm",
        tool_choice=None,
        tool_count=0,
        message_count=len(messages),
        elapsed_ms=elapsed_ms,
        tool_names=[],
    )
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
    caller: Optional[str] = None,
    request_tag: Optional[str] = None,
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
    tool_block_order: List[int] = []

    def handle_delta(text: str) -> None:
        if text:
            chunks.append(text)
        if on_delta:
            on_delta(text)

    def track_tool_block(idx: int, block: Dict[str, Any]) -> None:
        if idx not in tool_blocks:
            tool_blocks[idx] = block
            tool_block_order.append(idx)

    def _call_stream() -> Any:
        with client.messages.stream(**payload) as stream:
            for event in stream:
                event_type = getattr(event, "type", "")
                if event_type == "content_block_start":
                    block = getattr(event, "content_block", None)
                    block_type = getattr(block, "type", None)
                    if block_type is None and isinstance(block, dict):
                        block_type = block.get("type")
                    if block_type == "tool_use":
                        idx = getattr(event, "index", None)
                        if idx is None and isinstance(event, dict):
                            idx = event.get("index")
                        if idx is None:
                            idx = getattr(event, "content_block_index", None)
                        if idx is None and isinstance(event, dict):
                            idx = event.get("content_block_index")
                        if idx is None:
                            idx = max(tool_blocks.keys(), default=-1) + 1
                        block_id = getattr(block, "id", None) if not isinstance(block, dict) else block.get("id")
                        block_name = getattr(block, "name", None) if not isinstance(block, dict) else block.get("name")
                        block_input = (
                            getattr(block, "input", None) if not isinstance(block, dict) else block.get("input")
                        )
                        track_tool_block(int(idx), {
                            "id": block_id,
                            "name": block_name,
                            "input": block_input,
                            "buffer": "",
                        })
                elif event_type == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    if delta:
                        text = getattr(delta, "text", None)
                        if text is None and isinstance(delta, dict):
                            text = delta.get("text")
                        if text:
                            handle_delta(text)
                        delta_type = getattr(delta, "type", None)
                        if delta_type is None and isinstance(delta, dict):
                            delta_type = delta.get("type")
                        if delta_type == "input_json_delta":
                            idx = getattr(event, "index", None)
                            if idx is None and isinstance(event, dict):
                                idx = event.get("index")
                            if idx is None:
                                idx = getattr(event, "content_block_index", None)
                            if idx is None and isinstance(event, dict):
                                idx = event.get("content_block_index")
                            if idx is None:
                                continue
                            block = tool_blocks.get(int(idx))
                            if block is not None:
                                partial = getattr(delta, "partial_json", None)
                                if partial is None and isinstance(delta, dict):
                                    partial = delta.get("partial_json")
                                if partial:
                                    block["buffer"] += partial
                elif event_type == "content_block_stop":
                    idx = getattr(event, "index", None)
                    if idx is None and isinstance(event, dict):
                        idx = event.get("index")
                    if idx is None:
                        idx = getattr(event, "content_block_index", None)
                    if idx is None and isinstance(event, dict):
                        idx = event.get("content_block_index")
                    if idx is None:
                        continue
                    block = tool_blocks.get(int(idx))
                    if block is not None and block.get("buffer"):
                        try:
                            block["input"] = json.loads(block["buffer"])
                        except json.JSONDecodeError:
                            pass
            return stream.get_final_message()

    start = time.perf_counter()
    request_id = uuid.uuid4().hex
    message = _call_stream()
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info("Anthropic streaming completed ms=%.1f messages=%d", elapsed_ms, len(messages))
    parsed_text, tool_calls = _parse_anthropic_response(message)
    recovered: List[Dict[str, Any]] = []
    if tool_blocks:
        indices = tool_block_order or sorted(tool_blocks.keys())
        for idx in indices:
            block = tool_blocks.get(idx)
            if not block:
                continue
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
        def _tool_key(call: Dict[str, Any]) -> str:
            call_id = call.get("id")
            if call_id:
                return f"id:{call_id}"
            fn = call.get("function") or {}
            name = fn.get("name") or ""
            args = fn.get("arguments") or ""
            return f"sig:{name}:{args}"

        merged: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for call in recovered + tool_calls:
            key = _tool_key(call)
            if key in seen:
                continue
            seen.add(key)
            merged.append(call)
        tool_calls = merged
    tool_names: List[str] = []
    seen_names: set[str] = set()
    for call in tool_calls:
        fn = call.get("function") or {}
        name = fn.get("name")
        if name and name not in seen_names:
            seen_names.add(name)
            tool_names.append(name)
    _record_tokens(
        request_id=request_id,
        message=message,
        model=payload["model"],
        caller=caller,
        request_tag=request_tag,
        function_name="call_llm_with_tools",
        tool_choice=tool_choice,
        tool_count=len(tools) if tools else 0,
        message_count=len(messages),
        elapsed_ms=elapsed_ms,
        tool_names=tool_names,
    )
    text = "".join(chunks) if chunks else parsed_text
    return text, tool_calls


def call_llm_stream(
    messages: List[Dict[str, Any]],
    *,
    max_completion_tokens: int = 60000,
    response_format: Optional[Dict[str, Any]] = None,
    on_delta: Callable[[str], None],
    caller: Optional[str] = None,
    request_tag: Optional[str] = None,
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
    request_id = uuid.uuid4().hex
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
    _record_tokens(
        request_id=request_id,
        message=message,
        model=payload["model"],
        caller=caller,
        request_tag=request_tag,
        function_name="call_llm_stream",
        tool_choice=None,
        tool_count=0,
        message_count=len(messages),
        elapsed_ms=elapsed_ms,
        tool_names=[],
    )
    return text
