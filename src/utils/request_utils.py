"""Utilities for making API requests."""

import json
import os
from pathlib import Path

from PIL import Image

from src.lemon.api.anthropic import (
    get_anthropic_client,
    make_image_request,
    make_request,
    make_simple_request,
)
from src.lemon.utils.image_utils import generate_green_image, image_to_base64
from src.lemon.utils.token_tracker import (
    get_token_stats,
    load_token_tracking,
    save_token_tracking,
    track_tokens,
)

# Retain TOKENS_FILE for backwards compatibility (used by some callers/tests).
TOKENS_FILE = Path(__file__).parent.parent.parent / "tokens.json"


__all__ = [
    "get_anthropic_client",
    "make_request",
    "make_simple_request",
    "generate_green_image",
    "image_to_base64",
    "make_image_request",
    "get_token_stats",
    "load_token_tracking",
    "save_token_tracking",
    "track_tokens",
    "TOKENS_FILE",
]
