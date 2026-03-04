import json
from typing import Any, Dict, List

from .types import LLMMessage


def _to_anthropic_blocks(content: str | List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert content string or list of dicts to Anthropic content blocks."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content


def _to_anthropic_messages(messages: List[LLMMessage]) -> List[Dict[str, Any]]:
    """Convert standard LLMMessage format to Anthropic's alternating role format.

    Handles:
    1. Alternating user/assistant roles.
    2. Tool results (role='tool') merged into the preceding user message
       (Anthropic requirement for tool result batches).
    3. Tool calls (assistant role with tool_use blocks).
    """
    converted: List[Dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")

        if role == "system":
            # System prompt is handled separately by the client
            continue

        if role == "tool":
            tool_call_id = msg.get("tool_call_id") or msg.get("id") or ""
            tool_result_block = {
                "type": "tool_result",
                "tool_use_id": tool_call_id,
                "content": content
                if isinstance(content, (str, list))
                else json.dumps(content, ensure_ascii=True),
            }
            # Anthropic requires all tool results in a single "user" message
            # following the "assistant" message that made the tool calls.
            if (
                converted
                and converted[-1].get("role") == "user"
                and isinstance(converted[-1].get("content"), list)
                and converted[-1]["content"]
                and converted[-1]["content"][0].get("type") == "tool_result"
            ):
                converted[-1]["content"].append(tool_result_block)
            else:
                converted.append({"role": "user", "content": [tool_result_block]})
            continue

        if role == "assistant" and msg.get("tool_calls"):
            blocks = _to_anthropic_blocks(content)
            for call in msg["tool_calls"]:
                tool_call_id = call.get("id") or ""
                fn = call.get("function") or {}
                name = fn.get("name") or ""
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
                        "id": tool_call_id,
                        "name": name,
                        "input": args,
                    }
                )
            converted.append({"role": "assistant", "content": blocks})
            continue

        # Standard user/assistant messages
        converted.append({"role": role, "content": _to_anthropic_blocks(content)})

    return converted
