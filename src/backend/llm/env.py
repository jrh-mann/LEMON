"""Environment and client helpers for the LLM."""

from __future__ import annotations

import os
from typing import Optional

from anthropic import AnthropicFoundry


class LLMConfigError(RuntimeError):
    """Raised when LLM environment is missing or invalid."""


_REQUIRED_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_ENDPOINT", "ANTHROPIC_MODEL")

_USAGE_MESSAGE = (
    "Required environment variables:\n"
    "  ANTHROPIC_API_KEY=<your-api-key>\n"
    "  ANTHROPIC_ENDPOINT=<your-endpoint-url>\n"
    "  ANTHROPIC_MODEL=<model-name>\n"
)


def _require_env(name: str) -> str:
    """Return the value of an env var or raise with a helpful message."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise LLMConfigError(f"Missing {name}.\n\n{_USAGE_MESSAGE}")
    return value


# Singleton client — created once, reused across all call_llm() invocations.
# SDK built-in retry handles 429 and 5xx with exponential backoff.
_client: Optional[AnthropicFoundry] = None


def get_anthropic_client() -> AnthropicFoundry:
    """Return a cached AnthropicFoundry client (singleton)."""
    global _client
    if _client is not None:
        return _client

    api_key = _require_env("ANTHROPIC_API_KEY")
    endpoint = _require_env("ANTHROPIC_ENDPOINT")

    # Ensure the endpoint ends with a trailing slash and includes /anthropic/
    normalized_endpoint = endpoint.rstrip("/") + "/"
    if "anthropic" not in normalized_endpoint.lower():
        normalized_endpoint = normalized_endpoint + "anthropic/"

    _client = AnthropicFoundry(
        api_key=api_key, base_url=normalized_endpoint, max_retries=2,
    )
    return _client


def get_anthropic_model() -> str:
    return _require_env("ANTHROPIC_MODEL")
