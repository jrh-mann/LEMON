"""Image utility functions."""

from __future__ import annotations

import base64
from io import BytesIO
from typing import Tuple

from PIL import Image


def image_to_base64(image: Image.Image, *, format: str = "PNG") -> str:
    """Convert a PIL image to base64-encoded bytes (utf-8 str)."""
    buffered = BytesIO()
    image.save(buffered, format=format)
    return base64.b64encode(buffered.getvalue()).decode("utf-8")


def detect_media_type_and_format(image: Image.Image) -> Tuple[str, str]:
    """Return (media_type, format_str) based on detected image format."""
    format_map = {
        "JPEG": ("image/jpeg", "JPEG"),
        "JPG": ("image/jpeg", "JPEG"),
        "PNG": ("image/png", "PNG"),
        "WEBP": ("image/webp", "WEBP"),
        "GIF": ("image/gif", "GIF"),
    }
    img_format = (image.format or "PNG").upper()
    return format_map.get(img_format, ("image/png", "PNG"))


def generate_green_image(width: int = 512, height: int = 512) -> Image.Image:
    """Generate a solid green image."""
    return Image.new("RGB", (width, height), color=(0, 255, 0))


