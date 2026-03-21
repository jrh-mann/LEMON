"""Anthropic message conversion helpers."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("backend.llm")


def _extract_system(messages: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
    system_parts = []
    rest: List[Dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") == "system":
            content = msg.get("content", "")
            if isinstance(content, str):
                system_parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        system_parts.append(block.get("text", ""))
            continue
        rest.append(msg)
    return "\n\n".join(system_parts), rest


def _to_anthropic_blocks(content: Any) -> List[Dict[str, Any]]:
    """Convert internal content representation to Anthropic API content blocks.

    Handles: text, image (base64), document (PDF), tool_result.
    All content is stored in native Anthropic format — no OpenAI conversion needed.
    """
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if isinstance(content, list):
        blocks: List[Dict[str, Any]] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            ptype = part.get("type")
            if ptype == "text":
                text = part.get("text", "")
                if text:
                    blocks.append({"type": "text", "text": text})
            elif ptype == "image":
                blocks.append({"type": "image", "source": part.get("source", {})})
            elif ptype == "document":
                blocks.append({"type": "document", "source": part.get("source", {})})
            elif ptype == "tool_result":
                # Tool results are stored in native Anthropic format — pass through
                blocks.append(part)
        return blocks
    fallback = json.dumps(content, ensure_ascii=True)
    return [{"type": "text", "text": fallback}] if fallback else []


def _build_message_blocks(msg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build Anthropic API content blocks for a single message.

    Handles thinking blocks (assistant), text/image/document/tool_result content,
    and tool_use blocks (assistant with tool_calls).
    """
    role = msg.get("role")
    blocks: List[Dict[str, Any]] = []
    # Thinking blocks must precede all other content per Anthropic API spec
    if role == "assistant":
        blocks.extend(msg.get("thinking_blocks") or [])
    # Convert content (text, images, tool_results, etc.)
    blocks.extend(_to_anthropic_blocks(msg.get("content", "")))
    # Tool calls stored as {id, name, input} — add "type": "tool_use" for API
    for call in (msg.get("tool_calls") or []):
        blocks.append({
            "type": "tool_use",
            "id": call.get("id") or "",
            "name": call.get("name"),
            "input": call.get("input") or {},
        })
    return blocks


def _to_anthropic_messages(
    messages: List[Dict[str, Any]],
) -> Tuple[str, List[Dict[str, Any]]]:
    """Convert internal message history to Anthropic API format.

    Extracts system messages, builds content blocks for each message,
    and merges consecutive same-role messages (e.g. batched tool results).
    """
    system, rest = _extract_system(messages)
    converted: List[Dict[str, Any]] = []
    for msg in rest:
        role = msg.get("role")
        if role not in {"user", "assistant"}:
            continue
        blocks = _build_message_blocks(msg)
        if not blocks:
            blocks = [{"type": "text", "text": "(empty)"}]
        # Merge consecutive same-role messages (e.g. batched tool results)
        if converted and converted[-1]["role"] == role:
            converted[-1]["content"].extend(blocks)
        else:
            converted.append({"role": role, "content": blocks})
    return system, converted


def _parse_anthropic_response(message: Any) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Parse an Anthropic SDK response into (text, tool_calls, thinking_blocks).

    Input is always an SDK Message object from stream.get_final_message().
    Content blocks are Pydantic models (TextBlock, ToolUseBlock, ThinkingBlock)
    so we access attributes directly — no dict fallback needed.
    """
    text_parts: List[str] = []
    tool_calls: List[Dict[str, Any]] = []
    thinking_blocks: List[Dict[str, Any]] = []
    for block in message.content or []:
        if block.type == "thinking":
            # Preserve full block including signature for API replay
            if block.thinking:
                thinking_blocks.append({
                    "type": "thinking",
                    "thinking": block.thinking,
                    "signature": block.signature,
                })
        elif block.type == "text":
            if block.text:
                text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append({
                "id": block.id,
                "name": block.name,
                "input": block.input or {},
            })
    return "".join(text_parts), tool_calls, thinking_blocks
