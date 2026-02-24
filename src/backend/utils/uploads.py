"""Shared helpers for saving uploaded images and annotations."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any, List
from uuid import uuid4

from .paths import lemon_data_dir

logger = logging.getLogger(__name__)


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
    # validate=True gives clearer failures for truncated/invalid base64 payloads.
    return base64.b64decode(b64, validate=True), ext


def save_uploaded_image(
    data_url: str,
    *,
    repo_root: Path,
    filename_prefix: str = "",
) -> str:
    raw, ext = decode_data_url(data_url)
    data_dir = lemon_data_dir(repo_root)
    uploads_dir = data_dir / "uploads"
    try:
        uploads_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        raise PermissionError(
            "Upload storage directory is not writable. "
            "Set LEMON_DATA_DIR to a writable path (e.g. /tmp/lemon or /home/lemon) for this deployment."
        ) from exc
    filename = f"{filename_prefix}{uuid4().hex}.{ext}"
    path = uploads_dir / filename
    try:
        path.write_bytes(raw)
    except PermissionError as exc:
        raise PermissionError(
            "Upload storage path is not writable. "
            "Set LEMON_DATA_DIR to a writable path (e.g. /tmp/lemon or /home/lemon) for this deployment."
        ) from exc
    return str(path.relative_to(data_dir))


def _annotations_path_for(image_path: Path) -> Path:
    """Return the .annotations.json sidecar path for a given image."""
    return image_path.with_suffix(image_path.suffix + ".annotations.json")


def save_annotations(
    image_rel_path: str,
    annotations: List[dict[str, Any]],
    *,
    repo_root: Path,
) -> None:
    """Persist annotations as a JSON sidecar next to the uploaded image.

    ``image_rel_path`` is either relative to lemon_data_dir **or** an absolute path.
    """
    data_dir = lemon_data_dir(repo_root)
    image_path = Path(image_rel_path)
    if not image_path.is_absolute():
        image_path = data_dir / image_path
    ann_path = _annotations_path_for(image_path)
    ann_path.write_text(json.dumps(annotations, indent=2), encoding="utf-8")
    logger.info("Saved %d annotations to %s", len(annotations), ann_path)


def load_annotations(
    image_path: Path,
    *,
    repo_root: Path,
) -> List[dict[str, Any]]:
    """Load annotations for an image, returning [] if none exist."""
    if not image_path.is_absolute():
        data_dir = lemon_data_dir(repo_root)
        image_path = data_dir / image_path
    ann_path = _annotations_path_for(image_path)
    if not ann_path.exists():
        return []
    try:
        data = json.loads(ann_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        logger.warning("Annotations file %s is not a list, ignoring", ann_path)
        return []
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load annotations from %s: %s", ann_path, exc)
        return []
