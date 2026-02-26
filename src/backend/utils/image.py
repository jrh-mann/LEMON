"""Shared helpers for image/file encoding."""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

# Anthropic API limit: 5 MB for base64 image data.
# Use 4.8 MB as target to leave a safe margin.
_MAX_IMAGE_BYTES = 4.8 * 1024 * 1024
_MAX_DIMENSION = 1568  # Anthropic recommended max dimension


def image_to_data_url(image_path: Path) -> str:
    """Read an image file, compress to stay under 5 MB, return a data URL."""
    raw = image_path.read_bytes()

    # If already small enough, encode directly
    if len(raw) <= _MAX_IMAGE_BYTES:
        return _encode_image_bytes(raw, image_path.suffix)

    # Resize and compress with Pillow
    return _compress_image(raw, image_path.suffix)


def file_to_data_url(file_path: Path) -> str:
    """Read an image or PDF file and return a data URL.

    Images are compressed to stay under the Anthropic 5 MB limit.
    PDFs are encoded as-is.
    """
    suffix = file_path.suffix.lower().lstrip(".")
    if suffix == "pdf":
        raw = file_path.read_bytes()
        encoded = base64.b64encode(raw).decode("ascii")
        return f"data:application/pdf;base64,{encoded}"

    # Image: delegate to image_to_data_url for compression
    return image_to_data_url(file_path)


def _encode_image_bytes(raw: bytes, suffix: str) -> str:
    """Encode raw image bytes to a data URL without compression."""
    suffix_clean = suffix.lower().lstrip(".")
    media_map = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
    }
    media_type = media_map.get(suffix_clean, "image/png")
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def _compress_image(raw: bytes, suffix: str) -> str:
    """Resize and compress an image to stay under _MAX_IMAGE_BYTES."""
    img = Image.open(io.BytesIO(raw))

    # Convert RGBA/palette to RGB for JPEG output
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")

    # Resize if either dimension exceeds the max
    w, h = img.size
    if max(w, h) > _MAX_DIMENSION:
        scale = _MAX_DIMENSION / max(w, h)
        new_w = max(1, round(w * scale))
        new_h = max(1, round(h * scale))
        img = img.resize((new_w, new_h), Image.LANCZOS)
        logger.info("Resized image from %dx%d to %dx%d", w, h, new_w, new_h)

    # Encode as JPEG, lowering quality until under the byte limit
    quality = 90
    while quality >= 30:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        data = buf.getvalue()
        if len(data) <= _MAX_IMAGE_BYTES:
            logger.info("Compressed image to %d bytes (quality=%d)", len(data), quality)
            encoded = base64.b64encode(data).decode("ascii")
            return f"data:image/jpeg;base64,{encoded}"
        quality -= 5

    # Last resort: return whatever we got at lowest quality
    logger.warning("Image still %d bytes after max compression", len(data))
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"
