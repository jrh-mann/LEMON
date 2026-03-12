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


def _to_anthropic_messages(
    messages: List[Dict[str, Any]],
) -> Tuple[str, List[Dict[str, Any]]]:
    system, rest = _extract_system(messages)
    converted: List[Dict[str, Any]] = []
    for msg in rest:
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "assistant" and msg.get("tool_calls"):
            blocks = []
            # Thinking blocks must precede text/tool_use per Anthropic API spec
            for tb in (msg.get("thinking_blocks") or []):
                blocks.append(tb)
            blocks.extend(_to_anthropic_blocks(content))
            # Tool calls are already in native Anthropic format {id, name, input}
            # — just add the "type": "tool_use" wrapper for the API content block.
            for call in msg.get("tool_calls") or []:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.get("id") or "",
                        "name": call.get("name"),
                        "input": call.get("input") if isinstance(call.get("input"), dict) else {},
                    }
                )
            if blocks:
                converted.append({"role": "assistant", "content": blocks})
            continue
        if role in {"user", "assistant"}:
            blocks = []
            # Thinking blocks precede text in assistant messages
            if role == "assistant":
                for tb in (msg.get("thinking_blocks") or []):
                    blocks.append(tb)
            blocks.extend(_to_anthropic_blocks(content))
            if not blocks:
                # Empty content — use placeholder to preserve alternation
                blocks = [{"type": "text", "text": "(empty)"}]
            # Merge consecutive same-role messages instead of creating duplicates
            if converted and converted[-1].get("role") == role:
                existing = converted[-1].get("content", [])
                if isinstance(existing, list):
                    existing.extend(blocks)
                else:
                    converted[-1]["content"] = [{"type": "text", "text": existing}] + blocks
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
