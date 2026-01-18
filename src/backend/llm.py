"""LLM client helpers."""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, List, Optional

import json
import time
from openai import AzureOpenAI
from openai import APIConnectionError, APIError, APITimeoutError, RateLimitError
from pathlib import Path


class LLMConfigError(RuntimeError):
    """Raised when LLM environment is missing or invalid."""

logger = logging.getLogger("backend.llm")

def _load_env() -> None:
    env_path = Path(__file__).parent.parent.parent / ".env"
    if not env_path.exists():
        return
    logger.debug("Loading env from %s", env_path)
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _get_deployment_name() -> str:
    deployment = (
        os.environ.get("DEPLOYMENT_NAME")
        or os.environ.get("AZURE_OPENAI_DEPLOYMENT")
        or os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME")
    )
    if not deployment:
        raise LLMConfigError("Missing DEPLOYMENT_NAME/AZURE_OPENAI_DEPLOYMENT.")
    return deployment


def _build_azure_url() -> str:
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT") or os.environ.get("ENDPOINT")
    deployment = _get_deployment_name()
    api_version = (
        os.environ.get("AZURE_OPENAI_API_VERSION")
        or os.environ.get("API_VERSION")
        or "2024-12-01-preview"
    )
    if not endpoint:
        raise LLMConfigError("Missing AZURE_OPENAI_ENDPOINT/ENDPOINT.")
    endpoint = endpoint.rstrip("/")
    if not endpoint.startswith("https://"):
        raise LLMConfigError("AZURE_OPENAI_ENDPOINT must start with https://")

    # If a full OpenAI URL is provided, reuse it.
    if "/openai/" in endpoint:
        if "api-version=" in endpoint:
            return endpoint
        joiner = "&" if "?" in endpoint else "?"
        return f"{endpoint}{joiner}api-version={api_version}"

    return f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"


def _get_azure_client() -> AzureOpenAI:
    _load_env()
    api_key = os.environ.get("AZURE_OPENAI_API_KEY") or os.environ.get("API_KEY")
    if not api_key:
        raise LLMConfigError("Missing AZURE_OPENAI_API_KEY/API_KEY.")
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT") or os.environ.get("ENDPOINT")
    api_version = (
        os.environ.get("AZURE_OPENAI_API_VERSION")
        or os.environ.get("API_VERSION")
        or "2024-12-01-preview"
    )
    if not endpoint:
        raise LLMConfigError("Missing AZURE_OPENAI_ENDPOINT/ENDPOINT.")
    endpoint = endpoint.rstrip("/")
    if not endpoint.startswith("https://"):
        raise LLMConfigError("AZURE_OPENAI_ENDPOINT must start with https://")
    return AzureOpenAI(
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=endpoint,
    )


def call_azure_openai(
    messages: List[Dict[str, Any]],
    *,
    max_completion_tokens: int = 60000,
    response_format: Optional[Dict[str, Any]] = None,
) -> str:
    """Call Azure OpenAI chat completions and return assistant text."""
    client = _get_azure_client()
    url = _build_azure_url()
    deployment = _get_deployment_name()
    payload = {
        "model": deployment,
        "messages": messages,
        "max_completion_tokens": max_completion_tokens,
    }
    if response_format:
        payload["response_format"] = response_format

    payload_bytes = json.dumps(payload).encode("utf-8")
    message_sizes = []
    message_previews = []
    for idx, msg in enumerate(messages):
        content = msg.get("content")
        if isinstance(content, str):
            size = len(content.encode("utf-8"))
            preview = content[:300]
        elif isinstance(content, list):
            serialized = json.dumps(content, ensure_ascii=True)
            size = len(serialized.encode("utf-8"))
            preview = serialized[:300]
        else:
            serialized = json.dumps(content, ensure_ascii=True)
            size = len(serialized.encode("utf-8"))
            preview = serialized[:300]
        message_sizes.append({"index": idx, "role": msg.get("role"), "bytes": size})
        message_previews.append(
            {
                "index": idx,
                "role": msg.get("role"),
                "preview": preview,
            }
        )

    logger.debug(
        "Calling Azure OpenAI url=%s messages=%d payload_bytes=%d max_completion_tokens=%d response_format=%s message_sizes=%s message_previews=%s",
        url,
        len(messages),
        len(payload_bytes),
        max_completion_tokens,
        bool(response_format),
        json.dumps(message_sizes, ensure_ascii=True),
        json.dumps(message_previews, ensure_ascii=True),
    )
    start = time.perf_counter()
    try:
        resp = client.chat.completions.create(**payload)
    except (APIConnectionError, APITimeoutError, APIError, RateLimitError) as exc:
        raise RuntimeError(
            f"Network error calling Azure OpenAI: {exc}. "
            "Check AZURE_OPENAI_ENDPOINT and network connectivity."
        ) from exc
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "Azure OpenAI non-streaming completed ms=%.1f messages=%d",
            elapsed_ms,
            len(messages),
        )
    raw = resp.model_dump_json()

    logger.debug("Azure OpenAI response bytes=%d", len(raw))

    choices = resp.choices or []
    if not choices:
        raise RuntimeError("Azure OpenAI returned no choices.")
    message = choices[0].message
    content = message.content if message else None
    if not content:
        raise RuntimeError("Azure OpenAI returned empty content.")
    return content


def call_azure_openai_stream(
    messages: List[Dict[str, Any]],
    *,
    max_completion_tokens: int = 60000,
    response_format: Optional[Dict[str, Any]] = None,
    on_delta: Callable[[str], None],
) -> str:
    """Call Azure OpenAI with streaming and return full assistant text."""
    client = _get_azure_client()
    deployment = _get_deployment_name()
    payload: Dict[str, Any] = {
        "model": deployment,
        "messages": messages,
        "max_completion_tokens": max_completion_tokens,
        "stream": True,
    }
    if response_format:
        payload["response_format"] = response_format

    logger.debug("Streaming Azure OpenAI url=%s messages=%d", _build_azure_url(), len(messages))
    chunks: List[str] = []
    start = time.perf_counter()
    try:
        stream = client.chat.completions.create(**payload)
        for event in stream:
            delta = event.choices[0].delta if event.choices else None
            content = delta.content if delta else None
            if content:
                chunks.append(content)
                on_delta(content)
    except (APIConnectionError, APITimeoutError, APIError, RateLimitError) as exc:
        logger.warning("Streaming error, falling back to non-streaming: %s", exc)
        return call_azure_openai(
            messages,
            max_completion_tokens=max_completion_tokens,
            response_format=response_format,
        )
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "Azure OpenAI streaming completed ms=%.1f messages=%d chunks=%d",
            elapsed_ms,
            len(messages),
            len(chunks),
        )

    return "".join(chunks)
