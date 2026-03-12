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
            elif ptype == "image_url":
                image = part.get("image_url") or {}
                url = image.get("url", "")
                if url.startswith("data:") and ";base64," in url:
                    header, b64 = url.split(";base64,", 1)
                    media_type = header.replace("data:", "") or "image/jpeg"
                    blocks.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        }
                    )
                else:
                    logger.warning("Unsupported image_url for Anthropic: %s", url[:80])
            elif ptype == "image":
                # Explicitly construct the image block to ensure clean structure
                blocks.append({"type": "image", "source": part.get("source", {})})
            elif ptype == "document":
                # Passthrough for Anthropic native PDF document content blocks
                blocks.append({"type": "document", "source": part.get("source", {})})
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
        if role == "tool":
            tool_call_id = msg.get("tool_call_id") or msg.get("id") or ""
            tool_result_block = {
                "type": "tool_result",
                "tool_use_id": tool_call_id,
                "content": content if isinstance(content, (str, list)) else json.dumps(content, ensure_ascii=True),
            }
            # Merge into the previous user message if it already contains
            # tool_result blocks (Anthropic requires all tool results from
            # one batch in a single "user" message — consecutive user
            # messages violate the alternating-role contract).
            if (
                converted
                and converted[-1].get("role") == "user"
                and isinstance(converted[-1].get("content"), list)
                and converted[-1]["content"]
                and converted[-1]["content"][0].get("type") == "tool_result"
            ):
                converted[-1]["content"].append(tool_result_block)
            else:
                converted.append(
                    {"role": "user", "content": [tool_result_block]}
                )
            continue
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
    """Parse an Anthropic API response into (text, tool_calls, thinking_blocks).

    Extracts text, tool_use, and thinking content blocks from the response.
    Thinking blocks are returned as full dicts (including signature) so they
    can be replayed in the conversation history for subsequent tool-loop calls.
    """
    content_blocks = getattr(message, "content", []) or []
    text_parts: List[str] = []
    tool_calls: List[Dict[str, Any]] = []
    thinking_blocks: List[Dict[str, Any]] = []
    for block in content_blocks:
        # Parentheses required: without them `A or B if C else D` parses as
        # `(A or B) if C else D`, returning None for non-dict SDK objects.
        btype = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
        if btype == "thinking":
            # Preserve full thinking block including signature for API replay
            if isinstance(block, dict):
                thinking_blocks.append(block)
            else:
                blk: Dict[str, Any] = {"type": "thinking"}
                for attr in ("thinking", "signature"):
                    val = getattr(block, attr, None)
                    if val is not None:
                        blk[attr] = val
                if blk.get("thinking"):
                    thinking_blocks.append(blk)
        elif btype == "text":
            text = getattr(block, "text", None) if not isinstance(block, dict) else block.get("text")
            if text:
                text_parts.append(text)
        elif btype == "tool_use":
            # Return native Anthropic format: {id, name, input: dict}
            name = getattr(block, "name", None) if not isinstance(block, dict) else block.get("name")
            tool_id = getattr(block, "id", None) if not isinstance(block, dict) else block.get("id")
            tool_input = getattr(block, "input", None) if not isinstance(block, dict) else block.get("input")
            tool_calls.append(
                {
                    "id": tool_id,
                    "name": name,
                    "input": tool_input if isinstance(tool_input, dict) else {},
                }
            )
    # Defensive dedup — get_final_message() should already be clean,
    # but guard against edge cases.
    if tool_calls:
        merged: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for call in tool_calls:
            call_id = call.get("id")
            key = f"id:{call_id}" if call_id else f"sig:{call.get('name', '')}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(call)
        tool_calls = merged
    return "".join(text_parts), tool_calls, thinking_blocks
