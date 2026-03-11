"""Unified LLM client.

Single entry point `call_llm()` handles all use cases:
  - Simple text completion (no tools, no streaming)
  - Streaming text (on_delta callback)
  - Tool-augmented calls (tools + optional streaming)

Returns an LLMResponse dataclass with text, tool_calls, and usage.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .anthropic import (
    _convert_openai_tools_to_anthropic,
    _parse_anthropic_response,
    _to_anthropic_messages,
)
from .env import get_anthropic_client, get_anthropic_model, load_env
from ..utils.tokens import record_token_usage
from ..utils.cancellation import CancellationError

logger = logging.getLogger("backend.llm")

_MAX_RETRIES = 3
_RETRY_BACKOFF = [2, 5]


@dataclass
class LLMResponse:
    """Result of a call_llm() invocation."""
    text: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    usage: Dict[str, Any] = field(default_factory=dict)


def call_llm(
    messages: List[Dict[str, Any]],
    *,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    on_delta: Optional[Callable[[str], None]] = None,
    on_thinking: Optional[Callable[[str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    thinking_budget: Optional[int] = None,
    caller: Optional[str] = None,
    request_tag: Optional[str] = None,
) -> LLMResponse:
    """Unified LLM call. Handles text, streaming, and tool use.

    Args:
        messages: Conversation messages (system/user/assistant/tool).
        tools: Tool schemas (Anthropic function-calling format). None = no tools.
        tool_choice: "auto", "any", "none", or a specific tool name.
        on_delta: Streaming callback for text chunks. None = collect internally.
        on_thinking: Callback for extended thinking chunks.
        should_cancel: Polling function — returns True to abort.
        thinking_budget: Token budget for extended thinking. None = disabled.
        caller: Tag for token usage tracking.
        request_tag: Sub-tag for token usage tracking.
    """
    load_env()
    client = get_anthropic_client()
    system, converted = _to_anthropic_messages(messages)

    # Build Anthropic API payload
    if tool_choice is None and tools:
        tool_choice = "auto"
    tool_payload = (
        _convert_openai_tools_to_anthropic(tools)
        if tools and tool_choice != "none"
        else []
    )

    payload: Dict[str, Any] = {
        "model": get_anthropic_model(),
        "max_tokens": 128000,
        "system": system,
        "messages": converted,
    }
    if tool_payload:
        payload["tools"] = tool_payload
    if tool_choice:
        choice_map = {"none": "none", "any": "any", "auto": "auto"}
        if tool_choice in choice_map:
            payload["tool_choice"] = {"type": choice_map[tool_choice]}
        else:
            payload["tool_choice"] = {"type": "tool", "name": tool_choice}
    if thinking_budget is not None:
        payload["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}

    # Accumulation state for streaming
    text_chunks: List[str] = []
    tool_blocks: Dict[int, Dict[str, Any]] = {}
    tool_block_order: List[int] = []

    def _stream_events() -> Any:
        """Stream the API response, accumulating text and tool blocks."""
        with client.messages.stream(**payload) as stream:
            for event in stream:
                if should_cancel and should_cancel():
                    _close_stream(stream)
                    raise CancellationError("LLM streaming cancelled.")
                _handle_stream_event(
                    event, text_chunks, tool_blocks, tool_block_order,
                    on_delta=on_delta, on_thinking=on_thinking,
                )
            if should_cancel and should_cancel():
                _close_stream(stream)
                raise CancellationError("LLM streaming cancelled.")
            return stream.get_final_message()

    def _on_retry(attempt: int, msg: str) -> None:
        text_chunks.clear()
        tool_blocks.clear()
        tool_block_order.clear()

    start = time.perf_counter()
    request_id = uuid.uuid4().hex
    message = _retry_api_call(_stream_events, on_retry=_on_retry)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info("Anthropic streaming completed ms=%.1f messages=%d", elapsed_ms, len(messages))

    # Parse the final message for text, tool_calls, and thinking
    parsed_text, parsed_tool_calls, parsed_thinking = _parse_anthropic_response(message)
    if parsed_thinking and on_thinking:
        on_thinking(parsed_thinking)

    # Merge streamed tool blocks with parsed tool calls (deduplicating by ID)
    tool_calls = _merge_tool_calls(tool_blocks, tool_block_order, parsed_tool_calls)

    # Record token usage for observability
    tool_names = list(dict.fromkeys(
        (call.get("function") or {}).get("name", "")
        for call in tool_calls
        if (call.get("function") or {}).get("name")
    ))
    _record_tokens(
        request_id=request_id, message=message, model=payload["model"],
        caller=caller, request_tag=request_tag,
        tool_choice=tool_choice, tool_count=len(tools) if tools else 0,
        message_count=len(messages), elapsed_ms=elapsed_ms,
        tool_names=tool_names,
    )

    text = "".join(text_chunks) if text_chunks else parsed_text
    if not text.strip() and not tool_calls:
        stop = getattr(message, "stop_reason", None) or "unknown"
        logger.warning(
            "call_llm returned empty text with no tool calls "
            "(stop_reason=%s, caller=%s, tag=%s, messages=%d)",
            stop, caller, request_tag, len(messages),
        )

    usage = _extract_usage(message)
    return LLMResponse(text=text, tool_calls=tool_calls, usage=usage)


# ------------------------------------------------------------------
# Backwards-compatible wrappers (thin shims for existing callers).
# These will be removed once all callers migrate to call_llm().
# ------------------------------------------------------------------

def call_llm_with_tools(
    messages: List[Dict[str, Any]],
    *,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    max_completion_tokens: int = 128000,
    on_delta: Optional[Callable[[str], None]] = None,
    caller: Optional[str] = None,
    request_tag: Optional[str] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    thinking_budget: Optional[int] = None,
    on_thinking: Optional[Callable[[str], None]] = None,
) -> tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
    """Legacy wrapper — returns (text, tool_calls, usage) tuple."""
    resp = call_llm(
        messages, tools=tools, tool_choice=tool_choice,
        on_delta=on_delta, on_thinking=on_thinking,
        should_cancel=should_cancel, thinking_budget=thinking_budget,
        caller=caller, request_tag=request_tag,
    )
    return resp.text, resp.tool_calls, resp.usage


def call_llm_stream(
    messages: List[Dict[str, Any]],
    *,
    max_completion_tokens: int = 128000,
    response_format: Optional[Dict[str, Any]] = None,
    on_delta: Callable[[str], None],
    caller: Optional[str] = None,
    request_tag: Optional[str] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    thinking_budget: Optional[int] = None,
    on_thinking: Optional[Callable[[str], None]] = None,
) -> str:
    """Legacy wrapper — returns text only."""
    resp = call_llm(
        messages, on_delta=on_delta, on_thinking=on_thinking,
        should_cancel=should_cancel, thinking_budget=thinking_budget,
        caller=caller, request_tag=request_tag,
    )
    return resp.text


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _handle_stream_event(
    event: Any,
    text_chunks: List[str],
    tool_blocks: Dict[int, Dict[str, Any]],
    tool_block_order: List[int],
    *,
    on_delta: Optional[Callable[[str], None]],
    on_thinking: Optional[Callable[[str], None]],
) -> None:
    """Process a single streaming event from the Anthropic API."""
    event_type = getattr(event, "type", "")

    if event_type == "content_block_start":
        block = getattr(event, "content_block", None)
        block_type = getattr(block, "type", None)
        if block_type is None and isinstance(block, dict):
            block_type = block.get("type")
        if block_type == "tool_use":
            idx = _get_event_index(event)
            if idx is None:
                idx = max(tool_blocks.keys(), default=-1) + 1
            _get_attr = lambda b, k: getattr(b, k, None) if not isinstance(b, dict) else b.get(k)
            if idx not in tool_blocks:
                tool_blocks[idx] = {
                    "id": _get_attr(block, "id"),
                    "name": _get_attr(block, "name"),
                    "input": _get_attr(block, "input"),
                    "buffer": "",
                }
                tool_block_order.append(idx)

    elif event_type == "content_block_delta":
        delta = getattr(event, "delta", None)
        if not delta:
            return
        delta_type = getattr(delta, "type", None)
        if delta_type is None and isinstance(delta, dict):
            delta_type = delta.get("type")

        if delta_type == "thinking_delta" and on_thinking:
            thinking_text = getattr(delta, "thinking", None)
            if thinking_text:
                on_thinking(thinking_text)
        elif delta_type == "input_json_delta":
            idx = _get_event_index(event)
            if idx is not None:
                block = tool_blocks.get(int(idx))
                if block is not None:
                    partial = getattr(delta, "partial_json", None)
                    if partial is None and isinstance(delta, dict):
                        partial = delta.get("partial_json")
                    if partial:
                        block["buffer"] += partial
        else:
            text = getattr(delta, "text", None)
            if text is None and isinstance(delta, dict):
                text = delta.get("text")
            if text:
                text_chunks.append(text)
                if on_delta:
                    on_delta(text)

    elif event_type == "content_block_stop":
        idx = _get_event_index(event)
        if idx is not None:
            block = tool_blocks.get(int(idx))
            if block is not None and block.get("buffer"):
                try:
                    block["input"] = json.loads(block["buffer"])
                except json.JSONDecodeError:
                    pass


def _get_event_index(event: Any) -> Optional[int]:
    """Extract the content block index from a streaming event."""
    for attr in ("index", "content_block_index"):
        val = getattr(event, attr, None)
        if val is None and isinstance(event, dict):
            val = event.get(attr)
        if val is not None:
            return int(val)
    return None


def _merge_tool_calls(
    streamed_blocks: Dict[int, Dict[str, Any]],
    block_order: List[int],
    parsed_calls: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge streamed tool blocks with parsed tool calls, deduplicating."""
    recovered: List[Dict[str, Any]] = []
    if streamed_blocks:
        for idx in (block_order or sorted(streamed_blocks.keys())):
            block = streamed_blocks.get(idx)
            if not block or not block.get("name"):
                continue
            try:
                args_text = json.dumps(block.get("input") or {}, ensure_ascii=True)
            except (TypeError, ValueError):
                args_text = "{}"
            recovered.append({
                "id": block.get("id"),
                "type": "function",
                "function": {"name": block["name"], "arguments": args_text},
            })

    if not recovered:
        return parsed_calls

    # Deduplicate by ID or signature
    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for call in recovered + parsed_calls:
        call_id = call.get("id")
        if call_id:
            key = f"id:{call_id}"
        else:
            fn = call.get("function") or {}
            key = f"sig:{fn.get('name', '')}:{fn.get('arguments', '')}"
        if key not in seen:
            seen.add(key)
            merged.append(call)
    return merged


def _retry_api_call(
    fn: Callable[[], Any],
    *,
    on_retry: Optional[Callable[[int, str], None]] = None,
) -> Any:
    """Retry an API call on transient errors."""
    for attempt in range(_MAX_RETRIES):
        try:
            return fn()
        except CancellationError:
            raise
        except Exception as exc:
            exc_name = type(exc).__name__
            is_retryable = any(
                kw in exc_name.lower()
                for kw in ("timeout", "rate", "overloaded", "server", "connection", "api")
            )
            if not is_retryable or attempt == _MAX_RETRIES - 1:
                raise
            delay = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
            logger.warning(
                "API call failed (attempt %d/%d), retrying in %ds: %s: %s",
                attempt + 1, _MAX_RETRIES, delay, exc_name, exc,
            )
            if on_retry:
                on_retry(attempt + 1, f"{exc_name}: {exc}")
            time.sleep(delay)
    raise RuntimeError("Retry loop exited unexpectedly")


def _close_stream(stream: Any) -> None:
    close = getattr(stream, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            logger.debug("Failed to close LLM stream", exc_info=True)


def _extract_usage(message: Any) -> Dict[str, Any]:
    usage = getattr(message, "usage", None)
    if usage is None and isinstance(message, dict):
        usage = message.get("usage")
    if usage is None:
        return {}

    def _get(f: str) -> Optional[int]:
        val = usage.get(f) if isinstance(usage, dict) else getattr(usage, f, None)
        return int(val) if isinstance(val, int) else None

    result: Dict[str, Any] = {}
    for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        val = _get(key)
        if val is not None:
            result[key] = val
    inp = result.get("input_tokens", 0)
    out = result.get("output_tokens", 0)
    if inp or out:
        result["total_tokens"] = inp + out
    return result


def _record_tokens(
    *,
    request_id: str,
    message: Any,
    model: str,
    caller: Optional[str],
    request_tag: Optional[str],
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
        "function": "call_llm",
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
