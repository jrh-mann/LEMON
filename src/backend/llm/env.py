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


# ---------------------------------------------------------------------------
# OpenAI / Azure OpenAI helpers
# ---------------------------------------------------------------------------

# Prefixes that identify OpenAI-compatible models on Azure AI Foundry.
# Prefixes/names routed to the OpenAI-compatible API path.
_OPENAI_PREFIXES = ("gpt-", "o1-", "o3-", "o4-", "deepseek-", "DeepSeek-", "kimi-", "llama4-", "Llama-")


def is_openai_model(model_id: str) -> bool:
    """Return True if *model_id* should be routed via the OpenAI API."""
    return any(model_id.startswith(p) for p in _OPENAI_PREFIXES)


def get_openai_client():
    """Build an AzureOpenAI client for OpenAI-compatible models.

    Prefers dedicated OPENAI_ENDPOINT/OPENAI_API_KEY env vars.
    Falls back to deriving from the Anthropic endpoint (stripping /anthropic).
    """
    load_env()
    try:
        from openai import AzureOpenAI
    except ImportError:
        raise LLMConfigError("openai package is required for OpenAI models. Install with: pip install openai")

    # Prefer dedicated OpenAI env vars, fall back to Anthropic vars.
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("API_KEY")
    endpoint = os.environ.get("OPENAI_ENDPOINT") or os.environ.get("ANTHROPIC_ENDPOINT") or os.environ.get("ENDPOINT")
    if not api_key:
        raise LLMConfigError("Missing OPENAI_API_KEY/ANTHROPIC_API_KEY.")
    if not endpoint:
        raise LLMConfigError("Missing OPENAI_ENDPOINT/ANTHROPIC_ENDPOINT.")

    # Strip /anthropic suffix if derived from Anthropic endpoint.
    base = endpoint.strip().rstrip("/")
    if base.lower().endswith("/anthropic"):
        base = base[: -len("/anthropic")]

    return AzureOpenAI(
        azure_endpoint=base,
        api_key=api_key,
        api_version="2025-03-01-preview",
    )
