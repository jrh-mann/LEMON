"""OpenAI / Azure OpenAI message conversion and response parsing.

Mirrors anthropic.py but for the OpenAI chat completions API.
Internal message format is already close to OpenAI's — the main conversion
needed is for image content blocks (Anthropic base64 → OpenAI image_url).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("backend.llm")


# ---------------------------------------------------------------------------
# Message conversion: internal format → OpenAI chat format
# ---------------------------------------------------------------------------


def _to_openai_messages(
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Convert internal message list to OpenAI chat completion format.

    Handles:
      - System messages (pass through)
      - User messages with mixed text/image content
      - Assistant messages with tool_calls
      - Tool result messages
      - Image blocks in Anthropic format → OpenAI image_url format
    """
    converted: List[Dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")

        # Tool result messages — already OpenAI-compatible.
        if role == "tool":
            tool_call_id = msg.get("tool_call_id") or msg.get("id") or ""
            result_content = content
            if not isinstance(result_content, str):
                result_content = json.dumps(result_content, ensure_ascii=True)
            converted.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": result_content,
            })
            continue

        # Assistant messages with tool calls.
        if role == "assistant" and msg.get("tool_calls"):
            entry: Dict[str, Any] = {
                "role": "assistant",
                "tool_calls": msg["tool_calls"],
            }
            # Include text content if present.
            if isinstance(content, str) and content.strip():
                entry["content"] = content
            elif isinstance(content, list):
                text = _extract_text_from_blocks(content)
                if text:
                    entry["content"] = text
            converted.append(entry)
            continue

        # System, user, assistant messages.
        if role in ("system", "user", "assistant"):
            if isinstance(content, str):
                converted.append({"role": role, "content": content})
            elif isinstance(content, list):
                # Convert content blocks to OpenAI format.
                openai_blocks = _convert_content_blocks(content)
                if openai_blocks:
                    converted.append({"role": role, "content": openai_blocks})
                else:
                    converted.append({"role": role, "content": ""})
            else:
                converted.append({"role": role, "content": str(content)})
            continue

        # Unknown role — pass through.
        converted.append(msg)

    return converted


def _convert_content_blocks(blocks: List[Any]) -> List[Dict[str, Any]]:
    """Convert a list of content blocks to OpenAI format.

    Handles Anthropic image blocks → OpenAI image_url blocks.
    """
    result: List[Dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")

        if btype == "text":
            text = block.get("text", "")
            if text:
                result.append({"type": "text", "text": text})

        elif btype == "image_url":
            # Already in OpenAI format.
            result.append(block)

        elif btype == "image":
            # Anthropic base64 image → OpenAI image_url.
            source = block.get("source", {})
            if source.get("type") == "base64":
                media_type = source.get("media_type", "image/jpeg")
                data = source.get("data", "")
                url = f"data:{media_type};base64,{data}"
                result.append({
                    "type": "image_url",
                    "image_url": {"url": url, "detail": "high"},
                })

        elif btype == "tool_result":
            # Tool results inside user messages (from Anthropic merging).
            # OpenAI handles these as separate tool role messages, so we
            # extract just the text here.
            content = block.get("content", "")
            if isinstance(content, str) and content:
                result.append({"type": "text", "text": content})

    return result


def _extract_text_from_blocks(blocks: List[Any]) -> str:
    """Extract plain text from a list of content blocks."""
    parts = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)


# ---------------------------------------------------------------------------
# Tool choice conversion
# ---------------------------------------------------------------------------


def _convert_tool_choice_to_openai(
    tool_choice: Optional[str],
) -> Optional[Any]:
    """Convert internal tool_choice to OpenAI format.

    Internal: "auto", "any", "none", or a specific tool name.
    OpenAI:   "auto", "required", "none", or {"type": "function", "function": {"name": "..."}}.
    """
    if tool_choice is None:
        return None
    if tool_choice == "auto":
        return "auto"
    if tool_choice == "none":
        return "none"
    if tool_choice == "any":
        return "required"
    # Specific tool name.
    return {"type": "function", "function": {"name": tool_choice}}


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_openai_response(
    message: Any,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Parse an OpenAI chat completion message into (text, tool_calls).

    Returns tool_calls in our internal format (same as OpenAI's).
    """
    text = ""
    tool_calls: List[Dict[str, Any]] = []

    # Extract text content.
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    if isinstance(content, str):
        text = content

    # Extract tool calls.
    raw_calls = getattr(message, "tool_calls", None)
    if raw_calls is None and isinstance(message, dict):
        raw_calls = message.get("tool_calls")

    if isinstance(raw_calls, list):
        for call in raw_calls:
            call_id = getattr(call, "id", None) or (call.get("id") if isinstance(call, dict) else None)
            fn = getattr(call, "function", None) or (call.get("function") if isinstance(call, dict) else None)
            if fn is None:
                continue
            name = getattr(fn, "name", None) or (fn.get("name") if isinstance(fn, dict) else None)
            arguments = getattr(fn, "arguments", None) or (fn.get("arguments") if isinstance(fn, dict) else None)
            tool_calls.append({
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": arguments or "{}"},
            })

    return text, tool_calls


def _extract_openai_usage(response: Any) -> Dict[str, Any]:
    """Extract token usage from an OpenAI response object."""
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return {}

    def _get(f: str) -> Optional[int]:
        val = getattr(usage, f, None) if not isinstance(usage, dict) else usage.get(f)
        return int(val) if isinstance(val, int) else None

    result: Dict[str, Any] = {}
    # OpenAI uses prompt_tokens/completion_tokens.
    inp = _get("prompt_tokens")
    out = _get("completion_tokens")
    if inp is not None:
        result["input_tokens"] = inp
    if out is not None:
        result["output_tokens"] = out
    if inp or out:
        result["total_tokens"] = (inp or 0) + (out or 0)
    return result
