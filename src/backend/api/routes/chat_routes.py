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
from ...storage.conversation_log import ConversationLogger
from ...utils.uploads import save_uploaded_image

logger = logging.getLogger("backend.api")


def register_chat_routes(
    app: FastAPI,
    *,
    conversation_store: ConversationStore,
    repo_root: Path,
    conversation_logger: Optional[ConversationLogger] = None,
) -> None:
    """Register chat endpoints on the FastAPI app.

    Args:
        app: FastAPI application instance.
        conversation_store: In-memory conversation manager.
        repo_root: Repository root path for image uploads.
        conversation_logger: SQLite audit log for persistent chat history.
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
        """Retrieve conversation history.

        Tries the in-memory ConversationStore first (has full orchestrator
        history). Falls back to the ConversationLogger SQLite DB which
        persists across server restarts.
        """
        # Try in-memory store first (richest data)
        convo = conversation_store.get(conversation_id)
        if convo:
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

        # Fall back to persistent ConversationLogger SQLite DB
        if conversation_logger:
            # Fetch messages AND tool calls so we can attach tool_calls to
            # the assistant response they belong to.
            entries = conversation_logger.get_conversation_timeline(
                conversation_id,
                entry_types=["user_message", "assistant_response", "tool_call"],
            )
            if entries:
                messages = []
                # Collect tool calls between each user message and the next
                # assistant response, then attach them to that response.
                pending_tool_calls: list[dict] = []
                for entry in entries:
                    etype = entry["entry_type"]
                    if etype == "tool_call":
                        pending_tool_calls.append({
                            "tool": entry.get("tool_name", ""),
                            "arguments": {},
                            "success": bool(entry.get("tool_success", 1)),
                        })
                    elif etype == "user_message":
                        pending_tool_calls = []
                        messages.append({
                            "id": f"{conversation_id}_{entry['seq']}",
                            "role": "user",
                            "content": entry.get("content", ""),
                            "timestamp": entry.get("timestamp", utc_now()),
                            "tool_calls": [],
                        })
                    elif etype == "assistant_response":
                        messages.append({
                            "id": f"{conversation_id}_{entry['seq']}",
                            "role": "assistant",
                            "content": entry.get("content", ""),
                            "timestamp": entry.get("timestamp", utc_now()),
                            "tool_calls": pending_tool_calls,
                        })
                        pending_tool_calls = []
                return JSONResponse(
                    {
                        "id": conversation_id,
                        "messages": messages,
                        "working": {},
                    }
                )

        return JSONResponse({"error": "conversation not found"}, status_code=404)

    app.include_router(router)
