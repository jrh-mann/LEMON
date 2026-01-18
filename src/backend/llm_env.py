"""Environment and client helpers for the LLM."""

from __future__ import annotations

import logging
import os
from pathlib import Path

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


def get_anthropic_client() -> AnthropicFoundry:
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
    return AnthropicFoundry(api_key=api_key, base_url=normalized_endpoint)


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
