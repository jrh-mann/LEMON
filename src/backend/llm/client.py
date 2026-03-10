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
from ..utils.cancellation import CancellationError

# Max retries for transient API errors (rate limits, timeouts, server errors)
_MAX_RETRIES = 3
_RETRY_BACKOFF = [2, 5]  # seconds between retries (exponential-ish)

# Per-model max output token limits (Anthropic-imposed)
_MODEL_MAX_TOKENS: Dict[str, int] = {
    "opus": 32000,
    "sonnet": 64000,
    "haiku": 8192,
}


def _cap_max_tokens(requested: int) -> int:
    """Return a high max_tokens value to avoid hitting limits with extended thinking."""
    return 128000


def _retry_api_call(
    fn: Callable[[], Any],
    *,
    on_retry: Optional[Callable[[int, str], None]] = None,
) -> Any:
    """Retry an API call on transient errors.

    Args:
        fn: Zero-arg callable that makes the API request.
        on_retry: Optional callback (attempt, error_msg) called before each retry
            so the caller can notify the user.

    Raises the last exception if all retries are exhausted.
    """
    for attempt in range(_MAX_RETRIES):
        try:
            return fn()
        except CancellationError:
            raise  # Never retry cancellation
        except Exception as exc:
            exc_name = type(exc).__name__
            is_retryable = any(
                keyword in exc_name.lower()
                for keyword in ("timeout", "rate", "overloaded", "server", "connection", "api")
            )
            if not is_retryable or attempt == _MAX_RETRIES - 1:
                raise
            delay = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
            msg = f"{exc_name}: {exc}"
            logger.warning("API call failed (attempt %d/%d), retrying in %ds: %s", attempt + 1, _MAX_RETRIES, delay, msg)
            if on_retry:
                on_retry(attempt + 1, msg)
            time.sleep(delay)
    # Unreachable, but satisfies type checker
    raise RuntimeError("Retry loop exited unexpectedly")


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


def _close_stream(stream: Any) -> None:
    close = getattr(stream, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            logger.debug("Failed to close LLM stream", exc_info=True)


def call_llm(
    messages: List[Dict[str, Any]],
    *,
    max_completion_tokens: int = 128000,
    response_format: Optional[Dict[str, Any]] = None,
    caller: Optional[str] = None,
    request_tag: Optional[str] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    thinking_budget: Optional[int] = None,
    on_thinking: Optional[Callable[[str], None]] = None,
) -> str:
    load_env()
    if response_format:
        logger.debug("response_format ignored for Anthropic")
    client = get_anthropic_client()
    system, converted = _to_anthropic_messages(messages)
    payload: Dict[str, Any] = {
        "model": get_anthropic_model(),
        "max_tokens": _cap_max_tokens(max_completion_tokens),
        "system": system,
        "messages": converted,
    }
    # Enable extended thinking when a budget is provided
    if thinking_budget is not None:
        payload["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
    chunks: List[str] = []

    def _on_delta(text: str) -> None:
        if text:
            chunks.append(text)

    def _call_stream_llm() -> Any:
        with client.messages.stream(**payload) as stream:
            for event in stream:
                if should_cancel and should_cancel():
                    _close_stream(stream)
                    raise CancellationError("LLM streaming cancelled.")
                event_type = getattr(event, "type", "")
                if event_type == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    delta_type = getattr(delta, "type", None)
                    if delta_type == "thinking_delta" and on_thinking:
                        thinking_text = getattr(delta, "thinking", None)
                        if thinking_text:
                            on_thinking(thinking_text)
                    else:
                        text = getattr(delta, "text", None)
                        if text:
                            _on_delta(text)
            if should_cancel and should_cancel():
                _close_stream(stream)
                raise CancellationError("LLM streaming cancelled.")
            return stream.get_final_message()

    def _notify_retry_llm(attempt: int, msg: str) -> None:
        chunks.clear()

    start = time.perf_counter()
    request_id = uuid.uuid4().hex
    message = _retry_api_call(_call_stream_llm, on_retry=_notify_retry_llm)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info("Anthropic streaming completed ms=%.1f messages=%d", elapsed_ms, len(messages))
    parsed_text, _, parsed_thinking = _parse_anthropic_response(message)
    # Deliver any thinking from the final message that wasn't streamed
    if parsed_thinking and on_thinking:
        on_thinking(parsed_thinking)
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
    max_completion_tokens: int = 128000,
    on_delta: Optional[Callable[[str], None]] = None,
    caller: Optional[str] = None,
    request_tag: Optional[str] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    thinking_budget: Optional[int] = None,
    on_thinking: Optional[Callable[[str], None]] = None,
) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
    """Returns (text, tool_calls, usage) where usage contains token counts."""
    load_env()
    if tool_choice is None and tools:
        tool_choice = "auto"
    client = get_anthropic_client()
    system, converted = _to_anthropic_messages(messages)
    tool_payload = [] if tool_choice == "none" else _convert_openai_tools_to_anthropic(tools)
    payload: Dict[str, Any] = {
        "model": get_anthropic_model(),
        "max_tokens": _cap_max_tokens(max_completion_tokens),
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
    # Enable extended thinking when a budget is provided
    if thinking_budget is not None:
        payload["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
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
                if should_cancel and should_cancel():
                    _close_stream(stream)
                    raise CancellationError("LLM streaming cancelled.")
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
                        delta_type = getattr(delta, "type", None)
                        if delta_type is None and isinstance(delta, dict):
                            delta_type = delta.get("type")
                        # Route thinking deltas to the on_thinking callback
                        if delta_type == "thinking_delta" and on_thinking:
                            thinking_text = getattr(delta, "thinking", None)
                            if thinking_text:
                                on_thinking(thinking_text)
                        else:
                            text = getattr(delta, "text", None)
                            if text is None and isinstance(delta, dict):
                                text = delta.get("text")
                            if text:
                                handle_delta(text)
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
            if should_cancel and should_cancel():
                _close_stream(stream)
                raise CancellationError("LLM streaming cancelled.")
            return stream.get_final_message()

    def _notify_retry(attempt: int, msg: str) -> None:
        # Reset accumulation state so the retry starts fresh.
        # Do NOT call on_delta here — it feeds into JSON tool-argument parsing
        # and would corrupt the stream with non-JSON text.
        chunks.clear()
        tool_blocks.clear()
        tool_block_order.clear()

    start = time.perf_counter()
    request_id = uuid.uuid4().hex
    message = _retry_api_call(_call_stream, on_retry=_notify_retry)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info("Anthropic streaming completed ms=%.1f messages=%d", elapsed_ms, len(messages))
    parsed_text, tool_calls, parsed_thinking = _parse_anthropic_response(message)
    # Deliver any thinking from the final message that wasn't streamed
    if parsed_thinking and on_thinking:
        on_thinking(parsed_thinking)
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
    # Log a warning when the LLM returns empty text with no tool calls.
    # This helps diagnose "blank response" issues (e.g. thinking-only output,
    # context overflow, or unexpected stop_reason).
    if not text.strip() and not tool_calls:
        stop = getattr(message, "stop_reason", None) or "unknown"
        logger.warning(
            "call_llm_with_tools returned empty text with no tool calls "
            "(stop_reason=%s, caller=%s, tag=%s, messages=%d)",
            stop, caller, request_tag, len(messages),
        )
    usage = _extract_usage(message)
    return text, tool_calls, usage


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
    load_env()
    if response_format:
        logger.debug("response_format ignored for Anthropic")
    client = get_anthropic_client()
    system, converted = _to_anthropic_messages(messages)
    payload: Dict[str, Any] = {
        "model": get_anthropic_model(),
        "max_tokens": _cap_max_tokens(max_completion_tokens),
        "system": system,
        "messages": converted,
    }
    # Enable extended thinking when a budget is provided
    if thinking_budget is not None:
        payload["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
    def _call_stream_direct() -> Any:
        with client.messages.stream(**payload) as stream:
            for event in stream:
                if should_cancel and should_cancel():
                    _close_stream(stream)
                    raise CancellationError("LLM streaming cancelled.")
                event_type = getattr(event, "type", "")
                if event_type == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    delta_type = getattr(delta, "type", None)
                    if delta_type == "thinking_delta" and on_thinking:
                        thinking_text = getattr(delta, "thinking", None)
                        if thinking_text:
                            on_thinking(thinking_text)
                    else:
                        text = getattr(delta, "text", None)
                        if text:
                            on_delta(text)
            if should_cancel and should_cancel():
                _close_stream(stream)
                raise CancellationError("LLM streaming cancelled.")
            return stream.get_final_message()

    def _notify_retry_stream(attempt: int, msg: str) -> None:
        # Log retry but do NOT inject into the response stream via on_delta —
        # that would pollute the orchestrator's streamed_chunks and history.
        logger.warning("Retrying streaming request (%d/%d): %s", attempt, _MAX_RETRIES, msg)

    start = time.perf_counter()
    request_id = uuid.uuid4().hex
    message = _retry_api_call(_call_stream_direct, on_retry=_notify_retry_stream)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info("Anthropic streaming completed ms=%.1f messages=%d", elapsed_ms, len(messages))
    text, _, parsed_thinking = _parse_anthropic_response(message)
    # Deliver any thinking from the final message that wasn't streamed
    if parsed_thinking and on_thinking:
        on_thinking(parsed_thinking)
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
