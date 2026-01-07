"""Anthropic client integration.

This module intentionally keeps a thin, dependency-minimal surface area so it can be
used both by the new `src.lemon` pipeline and the legacy `src.utils.request_utils`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from anthropic import Anthropic
from dotenv import load_dotenv
from PIL import Image

from ..utils.image_utils import image_to_base64
from ..utils.token_tracker import track_tokens


@dataclass(frozen=True)
class AnthropicConfig:
    endpoint: str
    deployment_name: str
    api_key: str


class AnthropicClient:
    def __init__(self, config: AnthropicConfig):
        self.config = config

    def messages_create(
        self, *, messages: List[Dict[str, Any]], max_tokens: int, system: Optional[str] = None
    ) -> Any:
        kwargs: Dict[str, Any] = {
            "model": self.config.deployment_name,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if system:
            kwargs["system"] = system
        client = Anthropic(api_key=self.config.api_key, base_url=self.config.endpoint)
        message = client.messages.create(**kwargs)
        track_tokens(message)
        return message


def _load_env() -> None:
    # Keep compatibility with legacy `.env` usage.
    load_dotenv()


def get_anthropic_client() -> AnthropicClient:
    """Construct an Anthropic client from environment variables."""
    _load_env()
    endpoint = os.getenv("ENDPOINT") or ""
    deployment_name = os.getenv("DEPLOYMENT_NAME") or ""
    api_key = os.getenv("API_KEY") or ""
    if not all([endpoint, deployment_name, api_key]):
        raise ValueError(
            "Missing required environment variables: ENDPOINT, DEPLOYMENT_NAME, or API_KEY"
        )
    return AnthropicClient(
        AnthropicConfig(endpoint=endpoint, deployment_name=deployment_name, api_key=api_key)
    )


def make_request(
    messages: List[Dict[str, Any]],
    max_tokens: int = 1024,
    model: Optional[str] = None,
    system: Optional[str] = None,
) -> Any:
    """Send a messages request to Anthropic (Foundry)."""
    _load_env()
    endpoint = os.getenv("ENDPOINT") or ""
    api_key = os.getenv("API_KEY") or ""
    if not endpoint or not api_key:
        raise ValueError("Missing required environment variables: ENDPOINT or API_KEY")

    if model is None:
        model = os.getenv("DEPLOYMENT_NAME")
        if not model:
            raise ValueError("DEPLOYMENT_NAME environment variable is required")

    client = Anthropic(api_key=api_key, base_url=endpoint)
    kwargs: Dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if system:
        kwargs["system"] = system
    message = client.messages.create(**kwargs)
    track_tokens(message)
    return message


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
    """Send an image+text request to Anthropic."""
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
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": img_base64},
                },
                {"type": "text", "text": prompt},
            ],
        }
    ]
    return make_request(messages, max_tokens=max_tokens, model=model)
