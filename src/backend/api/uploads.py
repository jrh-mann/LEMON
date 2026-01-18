"""Image upload helpers for the API server."""

from __future__ import annotations

import base64
from pathlib import Path
from uuid import uuid4


def decode_data_url(data_url: str) -> tuple[bytes, str]:
    if not data_url.startswith("data:"):
        raise ValueError("Image must be a data URL.")
    header, _, b64 = data_url.partition(",")
    if not b64:
        raise ValueError("Invalid data URL payload.")
    media_type = header.split(";")[0].replace("data:", "")
    ext = "png"
    if media_type == "image/jpeg":
        ext = "jpg"
    elif media_type == "image/webp":
        ext = "webp"
    elif media_type == "image/gif":
        ext = "gif"
    elif media_type == "image/bmp":
        ext = "bmp"
    return base64.b64decode(b64), ext


def save_uploaded_image(data_url: str, *, repo_root: Path) -> str:
    raw, ext = decode_data_url(data_url)
    uploads_dir = repo_root / ".lemon" / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}.{ext}"
    path = uploads_dir / filename
    path.write_bytes(raw)
    return str(path.relative_to(repo_root))
