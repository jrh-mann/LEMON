"""Tool for asking the user a clarification question inline in chat."""

from __future__ import annotations

from typing import Any, Dict, List

from ..core import Tool, ToolParameter


class AskQuestionTool(Tool):
    """Ask the user a question with optional clickable options.

    Questions appear as inline cards in the chat — no image coordinates,
    no annotation dots. The user clicks an option chip or types freely.
    """

    name = "ask_question"
    description = (
        "Ask the user a clarification question. Use this whenever you are "
        "UNSURE about any detail — a threshold, label, branch condition, or "
        "ambiguous text. Provide options when possible so the user can click "
        "instead of typing."
    )
    parameters = [
        ToolParameter(
            name="question",
            type="string",
            description="The question to ask the user.",
            required=True,
        ),
        ToolParameter(
            name="options",
            type="array",
            description=(
                "Optional clickable choices. Each item has 'label' (display text) "
                "and 'value' (sent back when clicked). Omit for free-text only."
            ),
            required=False,
        ),
    ]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        question = args.get("question")
        if not question:
            raise ValueError("question is required")

        options: List[Dict[str, str]] = args.get("options", []) or []

        return {
            "success": True,
            "action": "question_asked",
            "question": str(question),
            "options": options,
        }
