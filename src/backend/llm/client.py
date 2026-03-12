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
import httpx

from .anthropic import (
    _parse_anthropic_response,
    _to_anthropic_messages,
)
from .env import get_anthropic_client, get_anthropic_model
from ..utils.tokens import record_token_usage
from ..utils.cancellation import CancellationError

logger = logging.getLogger("backend.llm")

_MAX_RETRIES = 3
_RETRY_BACKOFF = [2, 5]
# Rate limit retries use longer delays — the API typically says "wait 60s"
_RATE_LIMIT_MAX_RETRIES = 3
_RATE_LIMIT_BACKOFF = [30, 60, 60]


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
        messages: Conversation messages (system/user/assistant/tool).
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
        choice_map = {"none": "none", "any": "any", "auto": "auto"}
        if tool_choice in choice_map:
            payload["tool_choice"] = {"type": choice_map[tool_choice]}
        else:
            payload["tool_choice"] = {"type": "tool", "name": tool_choice}
    if thinking:
        payload["thinking"] = {"type": "adaptive"}
    if effort:
        payload["output"] = {"effort": effort}

    # Text accumulation for on_delta streaming callback and cancel recovery.
    # Tool calls come from get_final_message() — no streaming assembly needed.
    text_chunks: List[str] = []

    def _stream_events() -> Any:
        """Stream the API response, forwarding text/thinking deltas."""
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
            return stream.get_final_message()

    def _on_retry(attempt: int, msg: str) -> None:
        text_chunks.clear()

    start = time.perf_counter()
    request_id = uuid.uuid4().hex
    message = _retry_api_call(
        _stream_events, on_retry=_on_retry, should_cancel=should_cancel,
    )
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

    Tool calls come from get_final_message() after streaming completes,
    so we only handle text_delta and thinking_delta here.
    """
    event_type = getattr(event, "type", "")

    if event_type == "content_block_delta":
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
        elif delta_type == "text_delta":
            text = getattr(delta, "text", None)
            if text is None and isinstance(delta, dict):
                text = delta.get("text")
            if text:
                text_chunks.append(text)
                if on_delta:
                    on_delta(text)


class LLMQuotaError(RuntimeError):
    """Raised when the API quota or rate limit is exceeded after retries.

    Provides a user-friendly message instead of raw API error text.
    """


def _is_quota_error(exc: Exception) -> bool:
    """Check if an exception is a hard quota/rate limit error."""
    return isinstance(exc, anthropic.RateLimitError)


def _retry_api_call(
    fn: Callable[[], Any],
    *,
    on_retry: Optional[Callable[[int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Any:
    """Retry an API call on transient errors including rate limits.

    Rate limit errors (429) are retried with longer backoff (30-60s) since
    the API typically recovers within a minute. Other transient errors
    (timeout, connection, server) use shorter backoff (2-5s).
    """
    rate_limit_attempts = 0

    for attempt in range(_MAX_RETRIES):
        try:
            return fn()
        except CancellationError:
            raise
        except Exception as exc:
            # Rate limit: retryable with longer backoff
            if _is_quota_error(exc):
                rate_limit_attempts += 1
                if rate_limit_attempts >= _RATE_LIMIT_MAX_RETRIES:
                    logger.warning(
                        "API rate limit exceeded after %d retries: %s",
                        rate_limit_attempts, exc,
                    )
                    raise LLMQuotaError(
                        "API rate limit exceeded after retrying. "
                        "Please wait a moment and try again."
                    ) from exc
                delay = _RATE_LIMIT_BACKOFF[
                    min(rate_limit_attempts - 1, len(_RATE_LIMIT_BACKOFF) - 1)
                ]
                logger.warning(
                    "Rate limited (attempt %d/%d), retrying in %ds",
                    rate_limit_attempts, _RATE_LIMIT_MAX_RETRIES, delay,
                )
                if on_retry:
                    on_retry(attempt + 1, f"Rate limited, retrying in {delay}s")
                # Check for cancellation during rate limit wait so user
                # isn't stuck waiting 60s with no way to abort.
                _interruptible_sleep(delay, should_cancel)
                continue

            # Other transient errors: timeout, connection, server.
            # With max_retries=0 on the SDK client, raw httpx transport
            # exceptions (ConnectTimeout, ReadTimeout, etc.) propagate
            # unwrapped — catch those too so we actually retry.
            is_retryable = isinstance(
                exc,
                (anthropic.APITimeoutError, anthropic.APIConnectionError,
                 anthropic.InternalServerError,
                 httpx.TimeoutException, httpx.ConnectError),
            )
            if not is_retryable or attempt == _MAX_RETRIES - 1:
                raise
            delay = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
            exc_name = type(exc).__name__
            logger.warning(
                "API call failed (attempt %d/%d), retrying in %ds: %s: %s",
                attempt + 1, _MAX_RETRIES, delay, exc_name, exc,
            )
            if on_retry:
                on_retry(attempt + 1, f"{exc_name}: {exc}")
            _interruptible_sleep(delay, should_cancel)
    raise RuntimeError("Retry loop exited unexpectedly")


def _interruptible_sleep(
    seconds: float,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> None:
    """Sleep in 1-second increments, checking for cancellation each tick."""
    for _ in range(int(seconds)):
        if should_cancel and should_cancel():
            raise CancellationError("Cancelled during retry backoff.")
        time.sleep(1)
    # Sleep any fractional remainder
    remainder = seconds - int(seconds)
    if remainder > 0:
        time.sleep(remainder)


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
