"""Tool for re-viewing an uploaded workflow image mid-conversation.

Returns the image as an Anthropic-compatible base64 content block so the
LLM can re-examine it without the user re-uploading.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any, Dict, List

from ..core import Tool, ToolParameter


class ViewImageTool(Tool):
    """Load an uploaded image from disk and return it as an image content block."""

    name = "view_image"
    description = (
        "Re-examine an uploaded workflow image. Returns the image so you can "
        "look at it again during the conversation."
    )
    parameters: List[ToolParameter] = []  # No params — uses session_state uploaded_files

    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        uploaded_files = session_state.get("uploaded_files", [])

        # Find first image in uploaded files
        image_file = next(
            (f for f in uploaded_files if f.get("file_type") == "image"),
            None,
        )
        if not image_file:
            return {"success": False, "error": "No uploaded image found in session."}

        image_path = Path(image_file["path"])
        if not image_path.is_absolute():
            # Resolve relative to repo root if available
            repo_root = session_state.get("repo_root")
            if repo_root:
                image_path = Path(repo_root) / image_path

        if not image_path.exists():
            return {"success": False, "error": f"Image file not found: {image_path}"}

        # Read and encode the image
        raw = image_path.read_bytes()
        b64 = base64.b64encode(raw).decode()

        # Determine media type from extension
        suffix = image_path.suffix.lower()
        media_type_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        media_type = media_type_map.get(suffix, f"image/{suffix.lstrip('.')}")

        self._logger.info("ViewImageTool returning image %s (%d bytes)", image_path.name, len(raw))

        return {
            "success": True,
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": b64},
                },
                {
                    "type": "text",
                    "text": f"Image: {image_file.get('name', image_path.name)}",
                },
            ],
        }
