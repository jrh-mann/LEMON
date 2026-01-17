"""LLM client helpers."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import json
import urllib.request
import urllib.error
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


def _build_azure_url() -> str:
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT") or os.environ.get("ENDPOINT")
    deployment = (
        os.environ.get("DEPLOYMENT_NAME")
        or os.environ.get("AZURE_OPENAI_DEPLOYMENT")
        or os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME")
    )
    api_version = (
        os.environ.get("AZURE_OPENAI_API_VERSION")
        or os.environ.get("API_VERSION")
        or "2024-12-01-preview"
    )
    if not endpoint or not deployment:
        raise LLMConfigError(
            "Missing AZURE_OPENAI_ENDPOINT/ENDPOINT or DEPLOYMENT_NAME."
        )
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


def call_azure_openai(
    messages: List[Dict[str, Any]],
    *,
    max_completion_tokens: int = 60000,
    response_format: Optional[Dict[str, Any]] = None,
) -> str:
    """Call Azure OpenAI chat completions and return assistant text."""
    _load_env()
    api_key = os.environ.get("AZURE_OPENAI_API_KEY") or os.environ.get("API_KEY")
    if not api_key:
        raise LLMConfigError("Missing AZURE_OPENAI_API_KEY/API_KEY.")

    url = _build_azure_url()
    payload = {
        "messages": messages,
        "max_completion_tokens": max_completion_tokens,
    }
    if response_format:
        payload["response_format"] = response_format
    headers = {
        "Content-Type": "application/json",
        "api-key": api_key,
    }

    payload_bytes = json.dumps(payload).encode("utf-8")
    logger.debug(
        "Calling Azure OpenAI url=%s messages=%d payload_bytes=%d max_completion_tokens=%d response_format=%s",
        url,
        len(messages),
        len(payload_bytes),
        max_completion_tokens,
        bool(response_format),
    )
    req = urllib.request.Request(
        url,
        data=payload_bytes,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Azure OpenAI HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Network error calling Azure OpenAI: {exc}. "
            "Check AZURE_OPENAI_ENDPOINT and network connectivity."
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error calling Azure OpenAI")
        raise

    logger.debug("Azure OpenAI response bytes=%d", len(raw))

    data = json.loads(raw)
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(
            f"Azure OpenAI returned no choices. Response: {json.dumps(data)[:1000]}"
        )
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not content:
        raise RuntimeError(
            f"Azure OpenAI returned empty content. Response: {json.dumps(data)[:1000]}"
        )
    return content
