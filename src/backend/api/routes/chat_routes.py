"""Chat routes: send message and retrieve conversation history.

Handles the REST-based chat endpoint (POST /api/chat) and
conversation retrieval (GET /api/chat/<id>).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, FastAPI, Request
from starlette.responses import JSONResponse

from ..common import utc_now
from ..conversations import ConversationStore
from ..deps import require_auth
from ..response_utils import extract_flowchart, extract_tool_calls, summarize_response
from ...storage.auth import AuthUser
from ...utils.uploads import save_uploaded_image

logger = logging.getLogger("backend.api")


def register_chat_routes(
    app: FastAPI,
    *,
    conversation_store: ConversationStore,
    repo_root: Path,
) -> None:
    """Register chat endpoints on the FastAPI app.

    Args:
        app: FastAPI application instance.
        conversation_store: In-memory conversation manager.
        repo_root: Repository root path for image uploads.
    """
    router = APIRouter()

    @router.post("/api/chat")
    async def chat(
        request: Request,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = {}

        message = payload.get("message", "")
        conversation_id = payload.get("conversation_id")
        image_data = payload.get("image")

        if not isinstance(message, str) or not message.strip():
            return JSONResponse({"error": "message is required"}, status_code=400)

        convo = conversation_store.get_or_create(conversation_id)
        if isinstance(image_data, str) and image_data.strip():
            try:
                save_uploaded_image(image_data, repo_root=repo_root)
            except Exception as exc:
                logger.exception("Failed to save uploaded image")
                return JSONResponse(
                    {"error": f"Invalid image data: {exc}"}, status_code=400
                )

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
        return JSONResponse(
            {
                "conversation_id": convo.id,
                "response": response_summary,
                "tool_calls": tool_calls,
                "flowchart": flowchart,
            }
        )

    @router.get("/api/chat/{conversation_id}")
    async def get_conversation(
        conversation_id: str,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        convo = conversation_store.get(conversation_id)
        if not convo:
            return JSONResponse({"error": "conversation not found"}, status_code=404)
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
        return JSONResponse(
            {
                "id": convo.id,
                "messages": messages,
                "working": {},
                "created_at": convo.created_at,
                "updated_at": convo.updated_at,
            }
        )

    app.include_router(router)
