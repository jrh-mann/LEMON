"""Tool for asking the user clarification questions inline in chat."""

from __future__ import annotations

from typing import Any, Dict, List

from ..core import Tool, ToolParameter


class AskQuestionTool(Tool):
    """Ask the user one or more clarification questions.

    Questions appear as inline cards in the chat — the user clicks an
    option chip or types freely via the auto-added "Other" button.
    Multiple questions are shown sequentially; the model resumes only
    after all are answered.
    """

    name = "ask_question"
    description = (
        "Ask the user one or more clarification questions. Use this whenever "
        "you are UNSURE about any detail — a threshold, label, branch condition, "
        "or ambiguous text. Provide options when possible so the user can click "
        "instead of typing. Do NOT guess; ask. You may batch multiple questions."
    )
    parameters = [
        ToolParameter(
            name="questions",
            type="array",
            description=(
                "Array of questions. Each has 'question' (text) and optional "
                "'options' (clickable choices). Do NOT include 'Other' — the "
                "UI adds one automatically."
            ),
            required=True,
            items={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question text.",
                    },
                    "options": {
                        "type": "array",
                        "description": "Optional clickable choices (2-4 recommended).",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {
                                    "type": "string",
                                    "description": "Display text for the option.",
                                },
                                "value": {
                                    "type": "string",
                                    "description": "Value sent back when user clicks this option.",
                                },
                            },
                            "required": ["label", "value"],
                        },
                    },
                },
                "required": ["question"],
            },
        ),
    ]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        questions = args.get("questions")
        if not questions or not isinstance(questions, list):
            return {"success": False, "error": "questions array is required"}

        # Normalize each question entry
        normalized: List[Dict[str, Any]] = []
        for q in questions:
            if isinstance(q, str):
                # Allow bare strings as shorthand for option-less questions
                normalized.append({"question": q, "options": []})
            elif isinstance(q, dict):
                text = q.get("question", "")
                if not text:
                    continue
                normalized.append({
                    "question": str(text),
                    "options": q.get("options", []) or [],
                })

        if not normalized:
            return {"success": False, "error": "at least one question is required"}

        return {
            "success": True,
            "action": "question_asked",
            "questions": normalized,
        }
