"""Shared helpers for the backend."""

from __future__ import annotations

import base64
from pathlib import Path


def image_to_data_url(image_path: Path) -> str:
    """Read an image file and return a data URL."""
    return file_to_data_url(image_path)


def file_to_data_url(file_path: Path) -> str:
    """Read an image or PDF file and return a data URL."""
    suffix = file_path.suffix.lower().lstrip(".")
    if suffix == "pdf":
        media_type = "application/pdf"
    elif suffix in {"jpg", "jpeg"}:
        media_type = "image/jpeg"
    elif suffix == "webp":
        media_type = "image/webp"
    elif suffix == "gif":
        media_type = "image/gif"
    else:
        media_type = "image/png"

    raw = file_path.read_bytes()
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{media_type};base64,{encoded}"
