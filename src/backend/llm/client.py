"""Unified LLM client.

Single entry point `call_llm()` handles all use cases:
  - Simple text completion (no tools, no streaming)
  - Streaming text (on_delta callback)
  - Tool-augmented calls (tools + optional streaming)

Returns an LLMResponse dataclass with text, tool_calls, and usage.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import anthropic

from .anthropic import (
    _parse_anthropic_response,
    _to_anthropic_messages,
)
from .env import get_anthropic_client, get_anthropic_model
from ..utils.tokens import record_token_usage
from ..utils.cancellation import CancellationError

logger = logging.getLogger("backend.llm")


@dataclass
class LLMResponse:
    """Result of a call_llm() invocation."""
    text: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    thinking_blocks: List[Dict[str, Any]] = field(default_factory=list)
    usage: Dict[str, Any] = field(default_factory=dict)


def call_llm(
    messages: List[Dict[str, Any]],
    *,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    on_delta: Optional[Callable[[str], None]] = None,
    on_thinking: Optional[Callable[[str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    thinking: bool = False,
    effort: str = "high",
    caller: Optional[str] = None,
    request_tag: Optional[str] = None,
) -> LLMResponse:
    """Unified LLM call. Handles text, streaming, and tool use.

    Args:
        messages: Conversation messages (system/user/assistant).
        tools: Tool schemas (Anthropic function-calling format). None = no tools.
        tool_choice: "auto", "any", "none", or a specific tool name.
        on_delta: Streaming callback for text chunks. None = collect internally.
        on_thinking: Callback for extended thinking chunks.
        should_cancel: Polling function — returns True to abort.
        thinking: Enable adaptive thinking (Opus 4.6). False = disabled.
        effort: Thinking effort level ("low", "medium", "high", "max"). Default "high".
        caller: Tag for token usage tracking.
        request_tag: Sub-tag for token usage tracking.
    """
    client = get_anthropic_client()
    system, converted = _to_anthropic_messages(messages)

    system_payload = [{"type": "text", "text": system}] if system else []

    # Build Anthropic API payload
    if tool_choice is None and tools:
        tool_choice = "auto"
    # Tools are already in native Anthropic format from to_anthropic_schema()
    tool_payload = tools if tools and tool_choice != "none" else []

    payload: Dict[str, Any] = {
        "model": get_anthropic_model(),
        "max_tokens": 128000,
        "system": system_payload,
        "messages": converted,
    }
    if tool_payload:
        payload["tools"] = tool_payload
    if tool_choice:
        if tool_choice in {"none", "any", "auto"}:
            payload["tool_choice"] = {"type": tool_choice}
        else:
            # Specific tool name — force the model to call it
            payload["tool_choice"] = {"type": "tool", "name": tool_choice}
    if thinking:
        payload["thinking"] = {"type": "adaptive"}
    if effort:
        payload["output_config"] = {"effort": effort}

    # Text accumulation for on_delta streaming callback and cancel recovery.
    # Tool calls come from get_final_message() — no streaming assembly needed.
    text_chunks: List[str] = []

    start = time.perf_counter()
    request_id = uuid.uuid4().hex

    # Stream the API response, forwarding text/thinking deltas.
    # SDK handles retries for 429/5xx automatically (max_retries=2).
    with client.messages.stream(**payload) as stream:
        for event in stream:
            if should_cancel and should_cancel():
                _close_stream(stream)
                raise CancellationError("LLM streaming cancelled.")
            _handle_stream_event(
                event, text_chunks,
                on_delta=on_delta, on_thinking=on_thinking,
            )
        if should_cancel and should_cancel():
            _close_stream(stream)
            raise CancellationError("LLM streaming cancelled.")
        message = stream.get_final_message()
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info("Anthropic streaming completed ms=%.1f messages=%d", elapsed_ms, len(messages))

    # Parse the final message for text, tool_calls, and thinking.
    # get_final_message() returns complete, deduplicated content — no merge needed.
    # NOTE: do NOT re-emit parsed_thinking via on_thinking — the streaming
    # event loop already delivered thinking chunks in real time.
    text, tool_calls, parsed_thinking_blocks = _parse_anthropic_response(message)

    # Record token usage for observability
    tool_names = list(dict.fromkeys(
        call.get("name", "")
        for call in tool_calls
        if call.get("name")
    ))
    _record_tokens(
        request_id=request_id, message=message, model=payload["model"],
        caller=caller, request_tag=request_tag,
        tool_choice=tool_choice, tool_count=len(tools) if tools else 0,
        message_count=len(messages), elapsed_ms=elapsed_ms,
        tool_names=tool_names,
    )

    if not text.strip() and not tool_calls:
        stop = getattr(message, "stop_reason", None) or "unknown"
        logger.warning(
            "call_llm returned empty text with no tool calls "
            "(stop_reason=%s, caller=%s, tag=%s, messages=%d)",
            stop, caller, request_tag, len(messages),
        )

    usage = _extract_usage(message)
    return LLMResponse(text=text, tool_calls=tool_calls, thinking_blocks=parsed_thinking_blocks, usage=usage)


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _handle_stream_event(
    event: Any,
    text_chunks: List[str],
    *,
    on_delta: Optional[Callable[[str], None]],
    on_thinking: Optional[Callable[[str], None]],
) -> None:
    """Process a single streaming event — forward text and thinking deltas.

    Events are SDK Pydantic objects (direct attribute access).
    Tool calls come from get_final_message() after streaming completes,
    so we only handle text_delta and thinking_delta here.
    """
    if event.type != "content_block_delta":
        return
    delta = event.delta
    if delta.type == "thinking_delta" and on_thinking:
        if delta.thinking:
            on_thinking(delta.thinking)
    elif delta.type == "text_delta":
        if delta.text:
            text_chunks.append(delta.text)
            if on_delta:
                on_delta(delta.text)


def _close_stream(stream: Any) -> None:
    try:
        stream.close()
    except Exception:
        logger.debug("Failed to close LLM stream", exc_info=True)


def _extract_usage(message: Any) -> Dict[str, Any]:
    """Extract token usage from an SDK Message object.

    The SDK returns usage as a Pydantic Usage object with typed attributes.
    """
    usage = message.usage
    if usage is None:
        return {}
    result: Dict[str, Any] = {}
    for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        val = getattr(usage, key, None)
        if isinstance(val, int):
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
    provider_id = message.id
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
