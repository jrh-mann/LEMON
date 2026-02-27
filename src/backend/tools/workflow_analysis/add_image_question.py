"""Tool for adding LLM questions to the canvas."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

from ...utils.uploads import load_annotations, save_annotations
from ...utils.paths import lemon_data_dir
from ..core import Tool, ToolParameter


class AddImageQuestionTool(Tool):
    name = "add_image_question"
    description = (
        "Place a question dot on the user's workflow image at specific coordinates. "
        "Use this when you have a question about a specific part of the image."
    )
    parameters = [
        ToolParameter(
            name="image_name",
            type="string",
            description="The name of the uploaded image file (e.g. diagram.png).",
            required=True,
        ),
        ToolParameter(
            name="x",
            type="int",
            description="The X coordinate on the image where the question applies.",
            required=True,
        ),
        ToolParameter(
            name="y",
            type="int",
            description="The Y coordinate on the image where the question applies.",
            required=True,
        ),
        ToolParameter(
            name="question",
            type="string",
            description="The specific question you want to ask the user.",
            required=True,
        ),
    ]

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self._logger = logging.getLogger(__name__)

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        image_name = args.get("image_name")
        x = args.get("x")
        y = args.get("y")
        question = args.get("question")

        if not image_name or x is None or y is None or not question:
            raise ValueError("image_name, x, y, and question are required")

        try:
            x_val = int(x)
            y_val = int(y)
        except ValueError:
            raise ValueError("x and y must be integers")

        image_path = Path(image_name)
        if not image_path.is_absolute():
            image_path = self.repo_root / image_name

        annotations = load_annotations(image_path, repo_root=self.repo_root)

        # Check for duplicates before appending
        is_dup = False
        for a in annotations:
            if a.get("type") == "question" and a.get("question") == str(question):
                # If coordinates are very close (within 10 pixels), consider it a duplicate
                if abs(a.get("x", 0) - x_val) < 10 and abs(a.get("y", 0) - y_val) < 10:
                    is_dup = True
                    break

        if not is_dup:
            new_annotation = {
                "id": uuid4().hex[:8],
                "type": "question",
                "x": x_val,
                "y": y_val,
                "question": str(question),
                "status": "pending",
            }
            annotations.append(new_annotation)
            save_annotations(image_path, annotations, repo_root=self.repo_root)

        self._logger.info(
            "Added image question to %s at (%s, %s): %s",
            image_name,
            x_val,
            y_val,
            question,
        )

        return {
            "success": True,
            "action": "question_added",
            "annotations": annotations,
        }
