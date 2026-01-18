"""Anthropic message conversion helpers."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

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
                blocks.append(part)
        return blocks
    fallback = json.dumps(content, ensure_ascii=True)
    return [{"type": "text", "text": fallback}] if fallback else []


def _convert_openai_tools_to_anthropic(
    tools: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    if not tools:
        return []
    converted: List[Dict[str, Any]] = []
    for tool in tools:
        fn = tool.get("function") if isinstance(tool, dict) else None
        if not fn:
            continue
        converted.append(
            {
                "name": fn.get("name"),
                "description": fn.get("description") or "",
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return converted


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
            converted.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_call_id,
                            "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=True),
                        }
                    ],
                }
            )
            continue
        if role == "assistant" and msg.get("tool_calls"):
            blocks = _to_anthropic_blocks(content)
            for call in msg.get("tool_calls") or []:
                fn = call.get("function") or {}
                name = fn.get("name")
                args_text = fn.get("arguments") or "{}"
                if isinstance(args_text, str):
                    try:
                        args = json.loads(args_text)
                    except json.JSONDecodeError:
                        args = {}
                else:
                    args = args_text
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.get("id") or "",
                        "name": name,
                        "input": args if isinstance(args, dict) else {},
                    }
                )
            if blocks:
                converted.append({"role": "assistant", "content": blocks})
            continue
        if role in {"user", "assistant"}:
            blocks = _to_anthropic_blocks(content)
            if blocks:
                converted.append({"role": role, "content": blocks})
    return system, converted


def _parse_anthropic_response(message: Any) -> Tuple[str, List[Dict[str, Any]]]:
    content_blocks = getattr(message, "content", []) or []
    text_parts: List[str] = []
    tool_calls: List[Dict[str, Any]] = []
    for block in content_blocks:
        btype = getattr(block, "type", None) or block.get("type") if isinstance(block, dict) else None
        if btype == "text":
            text = getattr(block, "text", None) if not isinstance(block, dict) else block.get("text")
            if text:
                text_parts.append(text)
        elif btype == "tool_use":
            name = getattr(block, "name", None) if not isinstance(block, dict) else block.get("name")
            tool_id = getattr(block, "id", None) if not isinstance(block, dict) else block.get("id")
            tool_input = getattr(block, "input", None) if not isinstance(block, dict) else block.get("input")
            try:
                args_text = json.dumps(tool_input or {}, ensure_ascii=True)
            except (TypeError, ValueError):
                args_text = "{}"
            tool_calls.append(
                {
                    "id": tool_id,
                    "type": "function",
                    "function": {"name": name, "arguments": args_text},
                }
            )
    return "".join(text_parts), tool_calls
