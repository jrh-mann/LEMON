"""
Claude LLM client with extended thinking support for agentic workflows.
"""

import asyncio
from typing import Any, Callable, Dict, List, Optional

from anthropic import AnthropicFoundry

from .logging import get_logger


class ClaudeClient:
    """
    Claude client optimized for agentic task execution.
    Supports extended thinking for complex multi-step reasoning.
    """
    
    def __init__(
        self, 
        client: AnthropicFoundry, 
        model: str, 
        system_prompt: str, 
        max_tokens: int = 16000,
        thinking_budget: int = 10000,
        enable_thinking: bool = True
    ):
        self.client = client
        self.model = model
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.thinking_budget = thinking_budget
        self.enable_thinking = enable_thinking
        self.logger = get_logger("llm")

    def _build_payload(
        self, 
        messages: List[Dict[str, Any]], 
        tools: List[Dict[str, Any]],
        use_thinking: bool = True
    ) -> Dict[str, Any]:
        """
        Build the API payload with optional extended thinking.
        """
        payload: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": self.system_prompt,
            "messages": messages,
        }
        
        # Add tools if provided
        if tools:
            payload["tools"] = tools
        
        # Add extended thinking if enabled and model supports it
        if use_thinking and self.enable_thinking and self.thinking_budget > 0:
            payload["thinking"] = {
                "type": "enabled",
                "budget_tokens": self.thinking_budget
            }
        
        return payload

    async def complete(
        self, 
        messages: List[Dict[str, Any]], 
        tools: List[Dict[str, Any]],
        use_thinking: bool = True
    ) -> Any:
        """
        Call Claude asynchronously with optional extended thinking.
        """
        payload = self._build_payload(messages, tools, use_thinking)
        self.logger.info(
            "Sending %d messages to Claude (tools=%d, thinking=%s)", 
            len(messages), len(tools), use_thinking and self.enable_thinking
        )

        def _call():
            try:
                return self.client.messages.create(**payload)
            except Exception as e:
                # If thinking fails (unsupported model), retry without it
                if "thinking" in str(e).lower() or "budget" in str(e).lower():
                    self.logger.warning("Extended thinking not supported, retrying without it")
                    payload.pop("thinking", None)
                    return self.client.messages.create(**payload)
                raise

        return await asyncio.to_thread(_call)

    async def stream(
        self, 
        messages: List[Dict[str, Any]], 
        tools: List[Dict[str, Any]], 
        on_text: Callable[[str], None],
        on_thinking: Optional[Callable[[str], None]] = None,
        use_thinking: bool = True
    ) -> Any:
        """
        Stream Claude responses with optional extended thinking.
        Surfaces text deltas and thinking blocks as they arrive.
        """
        payload = self._build_payload(messages, tools, use_thinking)
        self.logger.info(
            "Streaming %d messages to Claude (tools=%d, thinking=%s)", 
            len(messages), len(tools), use_thinking and self.enable_thinking
        )

        def _call_stream():
            try:
                with self.client.messages.stream(**payload) as stream:
                    for event in stream:
                        try:
                            event_type = getattr(event, "type", "")
                            
                            if event_type == "content_block_delta":
                                delta = getattr(event, "delta", None)
                                if delta:
                                    # Handle text deltas
                                    text = getattr(delta, "text", None)
                                    if text:
                                        on_text(text)
                                    
                                    # Handle thinking deltas
                                    thinking = getattr(delta, "thinking", None)
                                    if thinking and on_thinking:
                                        on_thinking(thinking)
                        except Exception:
                            continue
                    return stream.get_final_message()
            except Exception as e:
                # If thinking fails, retry without it
                if "thinking" in str(e).lower() or "budget" in str(e).lower():
                    self.logger.warning("Extended thinking not supported in stream, retrying without it")
                    payload.pop("thinking", None)
                    with self.client.messages.stream(**payload) as stream:
                        for event in stream:
                            try:
                                if getattr(event, "type", "") == "content_block_delta":
                                    delta = getattr(event, "delta", None)
                                    text = getattr(delta, "text", None)
                                    if text:
                                        on_text(text)
                            except Exception:
                                continue
                        return stream.get_final_message()
                raise

        return await asyncio.to_thread(_call_stream)
