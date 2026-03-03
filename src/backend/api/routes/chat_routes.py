"""Chat routes: send message and retrieve conversation history.

Handles the REST-based chat endpoint (POST /api/chat) and
conversation retrieval (GET /api/chat/<id>).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Flask, jsonify, request

from ..common import utc_now
from ..conversations import ConversationStore
from ..response_utils import extract_flowchart, extract_tool_calls, summarize_response
from ...utils.uploads import save_uploaded_image

logger = logging.getLogger("backend.api")


def register_chat_routes(
    app: Flask,
    *,
    conversation_store: ConversationStore,
    repo_root: Path,
) -> None:
    """Register chat endpoints on the Flask app.

    Args:
        app: Flask application instance.
        conversation_store: In-memory conversation manager.
        repo_root: Repository root path for image uploads.
    """

    @app.post("/api/chat")
    def chat() -> Any:
        payload = request.get_json(force=True, silent=True) or {}
        message = payload.get("message", "")
        conversation_id = payload.get("conversation_id")
        image_data = payload.get("image")

        if not isinstance(message, str) or not message.strip():
            return jsonify({"error": "message is required"}), 400

        convo = conversation_store.get_or_create(conversation_id)
        if isinstance(image_data, str) and image_data.strip():
            try:
                save_uploaded_image(image_data, repo_root=repo_root)
            except Exception as exc:
                logger.exception("Failed to save uploaded image")
                return jsonify({"error": f"Invalid image data: {exc}"}), 400

        executed_tools: list[dict[str, Any]] = []

        def on_tool_event(
            event: str,
            tool: str,
            args: Dict[str, Any],
            result: Optional[Dict[str, Any]],
        ) -> None:
            if event == "tool_start":
                executed_tools.append({"tool": tool, "arguments": args})

        response_text = convo.orchestrator.respond(
            message,
            has_files=[],  # REST endpoint doesn't support multi-file yet
            allow_tools=True,
            on_tool_event=on_tool_event,
        )
        tool_calls = extract_tool_calls(response_text, include_result=False)
        if not tool_calls and executed_tools:
            tool_calls = executed_tools
        response_summary = summarize_response(response_text)
        flowchart = extract_flowchart(response_text)
        convo.updated_at = utc_now()
        return jsonify(
            {
                "conversation_id": convo.id,
                "response": response_summary,
                "tool_calls": tool_calls,
                "flowchart": flowchart,
            }
        )

    @app.get("/api/chat/<conversation_id>")
    def get_conversation(conversation_id: str) -> Any:
        convo = conversation_store.get(conversation_id)
        if not convo:
            return jsonify({"error": "conversation not found"}), 404
        messages = []
        for idx, msg in enumerate(convo.orchestrator.history):
            role = msg.get("role", "assistant")
            content = msg.get("content", "")
            messages.append(
                {
                    "id": f"{conversation_id}_{idx}",
                    "role": role,
                    "content": content,
                    "timestamp": utc_now(),
                    "tool_calls": extract_tool_calls(content),
                }
            )
        return jsonify(
            {
                "id": convo.id,
                "messages": messages,
                "working": {},
                "created_at": convo.created_at,
                "updated_at": convo.updated_at,
            }
        )
