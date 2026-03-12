"""Environment and client helpers for the LLM."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("backend.llm")

try:
    from anthropic import AnthropicFoundry
except ImportError:
    from anthropic import Anthropic
    AnthropicFoundry = Anthropic
    logger.warning(
        "AnthropicFoundry not available in anthropic package; using Anthropic fallback."
    )


class LLMConfigError(RuntimeError):
    """Raised when LLM environment is missing or invalid."""


def load_env() -> None:
    env_path = Path(__file__).parent.parent.parent.parent / ".env"
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


# Singleton client — created once, reused across all call_llm() invocations.
# max_retries=0 disables SDK built-in retry so our custom _retry_api_call()
# in client.py handles retries with cancel-awareness and LLMQuotaError fast-fail.
_client: Optional[AnthropicFoundry] = None


def get_anthropic_client() -> AnthropicFoundry:
    """Return a cached AnthropicFoundry client (singleton).

    First call loads .env and creates the client. Subsequent calls return
    the same instance, reusing the underlying HTTP connection pool.
    """
    global _client
    if _client is not None:
        return _client

    load_env()
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("API_KEY")
    endpoint = os.environ.get("ANTHROPIC_ENDPOINT") or os.environ.get("ENDPOINT")
    if not api_key:
        raise LLMConfigError("Missing ANTHROPIC_API_KEY/API_KEY.")
    if not endpoint:
        raise LLMConfigError("Missing ANTHROPIC_ENDPOINT/ENDPOINT.")
    normalized_endpoint = endpoint.strip().rstrip("/") + "/"
    if "anthropic" not in normalized_endpoint.lower():
        normalized_endpoint = normalized_endpoint + "anthropic/"
    _client = AnthropicFoundry(
        api_key=api_key, base_url=normalized_endpoint, max_retries=0,
    )
    return _client


def _reset_client() -> None:
    """Reset the singleton client. For testing only."""
    global _client
    _client = None


def get_anthropic_model() -> str:
    model = (
        os.environ.get("ANTHROPIC_MODEL")
        or os.environ.get("CLAUDE_MODEL")
        or os.environ.get("AGENT")
        or os.environ.get("MODEL")
    )
    if not model:
        raise LLMConfigError("Missing ANTHROPIC_MODEL/CLAUDE_MODEL/AGENT.")
    return model
