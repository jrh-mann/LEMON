"""Tool for re-viewing an uploaded workflow image mid-conversation.

Returns the image as an Anthropic-compatible base64 content block so the
LLM can re-examine it without the user re-uploading.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any, Dict, List

from ..core import Tool, ToolParameter, tool_error
from ...utils.image import detect_image_media_type


class ViewImageTool(Tool):
    """Load an uploaded image from disk and return it as an image content block."""

    name = "view_image"
    description = (
        "Re-examine an uploaded workflow image. Returns the image so you can "
        "look at it again during the conversation. When multiple images are "
        "uploaded, pass the filename to select a specific one."
    )
    parameters: List[ToolParameter] = [
        ToolParameter(
            name="filename",
            type="string",
            description="Name of the image file to view. If omitted, returns the first image. Use this when multiple images are uploaded.",
            required=False,
        ),
    ]

    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        uploaded_files = session_state.get("uploaded_files", [])
        requested_name = args.get("filename")

        # Collect all uploaded images
        images = [f for f in uploaded_files if f.get("file_type") == "image"]
        if not images:
            return tool_error("No uploaded image found in session.", "NO_IMAGE")

        # If a filename is specified, find that specific image
        if requested_name:
            image_file = next(
                (f for f in images if f.get("name") == requested_name),
                None,
            )
            if not image_file:
                available = [f.get("name", "?") for f in images]
                return tool_error(
                    f"Image '{requested_name}' not found. Available images: {available}",
                    "IMAGE_NOT_FOUND",
                )
        else:
            image_file = images[0]

        image_path = Path(image_file["path"])
        if not image_path.is_absolute():
            # Resolve relative to repo root if available
            repo_root = session_state.get("repo_root")
            if repo_root:
                image_path = Path(repo_root) / image_path

        if not image_path.exists():
            return tool_error(f"Image file not found: {image_path}", "FILE_NOT_FOUND")

        # Read and encode the image
        raw = image_path.read_bytes()
        b64 = base64.b64encode(raw).decode()

        # Detect media type from magic bytes (file extension can be wrong)
        media_type = detect_image_media_type(raw, image_path.suffix)

        self._logger.info("ViewImageTool returning image %s (%d bytes)", image_path.name, len(raw))

        # List all available image names so the LLM knows what else is uploaded
        available_names = [f.get("name", "?") for f in images]
        label = image_file.get("name", image_path.name)
        caption = f"Image: {label}"
        if len(images) > 1:
            caption += f" (uploaded images: {', '.join(available_names)})"

        return {
            "success": True,
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": b64},
                },
                {
                    "type": "text",
                    "text": caption,
                },
            ],
        }
