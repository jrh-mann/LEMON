"""Azure OpenAI client integration.

Historically this repo used Anthropic. The public functions in this module are kept
for backwards compatibility (`make_request`, `make_image_request`, etc.), but the
implementation targets **Azure OpenAI** via `openai.AzureOpenAI`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import AzureOpenAI
from PIL import Image

from ..utils.image_utils import image_to_base64
from ..utils.token_tracker import track_tokens


@dataclass(frozen=True)
class AzureOpenAIConfig:
    azure_endpoint: str
    api_key: str
    api_version: str
    deployment_name: str


class AzureOpenAIClient:
    def __init__(self, config: AzureOpenAIConfig):
        self.config = config
        self._client = AzureOpenAI(
            api_version=self.config.api_version,
            azure_endpoint=self.config.azure_endpoint,
            api_key=self.config.api_key,
        )

    def messages_create(
        self, *, messages: List[Dict[str, Any]], max_tokens: int, system: Optional[str] = None
    ) -> Any:
        # Convert the legacy/Anthropic-style message schema to OpenAI chat format.
        oai_messages: List[Dict[str, Any]] = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        oai_messages.extend(_to_openai_messages(messages))

        # GPT-5 expects `max_completion_tokens` in Azure OpenAI.
        try:
            resp = self._client.chat.completions.create(
                model=self.config.deployment_name,
                messages=oai_messages,  # type: ignore[arg-type]
                max_completion_tokens=max_tokens,
            )
        except TypeError:
            # Fallback for older SDKs/models.
            resp = self._client.chat.completions.create(
                model=self.config.deployment_name,
                messages=oai_messages,  # type: ignore[arg-type]
                max_tokens=max_tokens,
            )

        track_tokens(resp)
        return _wrap_openai_response(resp)

    def messages_create_stream(
        self, *, messages: List[Dict[str, Any]], max_tokens: int, system: Optional[str] = None
    ) -> Any:
        """Stream chat completion tokens. Yields text deltas."""
        from typing import Iterator

        # Convert the legacy/Anthropic-style message schema to OpenAI chat format.
        oai_messages: List[Dict[str, Any]] = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        oai_messages.extend(_to_openai_messages(messages))

        # Enable streaming in OpenAI API
        try:
            stream = self._client.chat.completions.create(
                model=self.config.deployment_name,
                messages=oai_messages,  # type: ignore[arg-type]
                max_completion_tokens=max_tokens,
                stream=True,
            )
        except TypeError:
            # Fallback for older SDKs/models.
            stream = self._client.chat.completions.create(
                model=self.config.deployment_name,
                messages=oai_messages,  # type: ignore[arg-type]
                max_tokens=max_tokens,
                stream=True,
            )

        for chunk in stream:
            # Type guard: check if chunk has choices attribute (ChatCompletionChunk)
            if hasattr(chunk, "choices"):
                if chunk.choices and len(chunk.choices) > 0:  # type: ignore[union-attr]
                    delta = chunk.choices[0].delta  # type: ignore[union-attr]
                    if hasattr(delta, "content") and delta.content:
                        yield delta.content
            # Track tokens from final chunk if available
            if hasattr(chunk, "usage") and getattr(chunk, "usage", None):
                track_tokens(chunk)


def _load_env() -> None:
    # Keep compatibility with legacy `.env` usage.
    load_dotenv()


def _get_azure_config(*, deployment_override: Optional[str] = None) -> AzureOpenAIConfig:
    _load_env()
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("ENDPOINT") or ""
    api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("API_KEY") or ""
    api_version = (
        os.getenv("AZURE_OPENAI_API_VERSION") or os.getenv("API_VERSION") or "2024-12-01-preview"
    )
    deployment_name = (
        deployment_override
        or os.getenv("AZURE_OPENAI_DEPLOYMENT")
        or os.getenv("DEPLOYMENT_NAME")
        or ""
    )
    if not all([azure_endpoint, deployment_name, api_key]):
        raise ValueError(
            "Missing required environment variables: AZURE_OPENAI_ENDPOINT/ENDPOINT, "
            "AZURE_OPENAI_DEPLOYMENT/DEPLOYMENT_NAME, AZURE_OPENAI_API_KEY/API_KEY"
        )
    return AzureOpenAIConfig(
        azure_endpoint=azure_endpoint,
        api_key=api_key,
        api_version=api_version,
        deployment_name=deployment_name,
    )


def get_anthropic_client() -> AzureOpenAIClient:
    """Back-compat alias; returns an Azure OpenAI client."""
    return AzureOpenAIClient(_get_azure_config())


def make_request(
    messages: List[Dict[str, Any]],
    max_tokens: int = 1024,
    model: Optional[str] = None,
    system: Optional[str] = None,
) -> Any:
    """Send a chat request to Azure OpenAI.

    `model` refers to the Azure deployment name.
    """
    cfg = _get_azure_config(deployment_override=model)
    client = AzureOpenAIClient(cfg)
    return client.messages_create(messages=messages, max_tokens=max_tokens, system=system)


def make_request_stream(
    messages: List[Dict[str, Any]],
    max_tokens: int = 1024,
    model: Optional[str] = None,
    system: Optional[str] = None,
) -> Any:
    """Stream a chat request to Azure OpenAI. Yields text chunks.

    `model` refers to the Azure deployment name.
    """
    from typing import Iterator

    cfg = _get_azure_config(deployment_override=model)
    client = AzureOpenAIClient(cfg)
    yield from client.messages_create_stream(messages=messages, max_tokens=max_tokens, system=system)


def make_simple_request(
    user_message: str, max_tokens: int = 1024, model: Optional[str] = None
) -> Any:
    return make_request(
        [{"role": "user", "content": user_message}], max_tokens=max_tokens, model=model
    )


def make_image_request(
    *,
    image: Image.Image | str,
    prompt: str,
    max_tokens: int = 1024,
    model: Optional[str] = None,
    image_format: str = "PNG",
) -> Any:
    """Send an image+text request to Azure OpenAI."""
    img: Image.Image = Image.open(image) if isinstance(image, str) else image

    img_base64 = image_to_base64(img, format=image_format)
    media_type_map = {
        "PNG": "image/png",
        "JPEG": "image/jpeg",
        "JPG": "image/jpeg",
        "WEBP": "image/webp",
        "GIF": "image/gif",
    }
    media_type = media_type_map.get(image_format.upper(), "image/png")

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": img_base64},
                },
            ],
        }
    ]
    return make_request(messages, max_tokens=max_tokens, model=model)


def _to_openai_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert legacy message format into OpenAI chat messages."""
    out: List[Dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")

        # Anthropic-style content array with image+text parts.
        if isinstance(content, list):
            parts: List[Dict[str, Any]] = []
            for part in content:
                if part.get("type") == "text":
                    parts.append({"type": "text", "text": part.get("text", "")})
                elif part.get("type") == "image":
                    src = part.get("source", {})
                    media_type = src.get("media_type", "image/png")
                    data = src.get("data", "")
                    parts.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{media_type};base64,{data}"},
                        }
                    )
            out.append({"role": role, "content": parts})
        else:
            # Plain string content.
            out.append({"role": role, "content": content})
    return out


class _WrappedText:
    def __init__(self, text: str):
        self.text = text


class _WrappedResponse:
    """Compatibility wrapper: exposes `.content[0].text` like Anthropic responses."""

    def __init__(self, text: str, usage: Any):
        self.content = [_WrappedText(text)]
        self.usage = usage


def _wrap_openai_response(resp: Any) -> Any:
    text = ""
    try:
        text = resp.choices[0].message.content or ""
    except Exception:
        text = ""
    return _WrappedResponse(text=text, usage=getattr(resp, "usage", None))
