"""Chat routes: send message and retrieve conversation history.

Handles the async chat endpoint (POST /api/chat/send) for guaranteed
message delivery, the legacy sync endpoint (POST /api/chat), and
conversation retrieval (GET /api/chat/<id>).
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, FastAPI, Request
from starlette.responses import JSONResponse

from ..common import utc_now
from ..conversations import ConversationStore
from ..deps import require_auth
from ..response_utils import extract_flowchart, extract_tool_calls, summarize_response
from ..ws_registry import ConnectionRegistry
from ...storage.auth import AuthUser
from ...storage.conversation_log import ConversationLogger
from ...storage.workflows import WorkflowStore
from ...utils.uploads import save_uploaded_image
from .helpers import api_error

logger = logging.getLogger("backend.api")


def register_chat_routes(
    app: FastAPI,
    *,
    conversation_store: ConversationStore,
    repo_root: Path,
    conversation_logger: Optional[ConversationLogger] = None,
    workflow_store: Optional[WorkflowStore] = None,
    ws_registry: Optional[ConnectionRegistry] = None,
) -> None:
    """Register chat endpoints on the FastAPI app.

    Args:
        app: FastAPI application instance.
        conversation_store: In-memory conversation manager.
        repo_root: Repository root path for image uploads.
        conversation_logger: SQLite audit log for persistent chat history.
        workflow_store: Workflow store for setting building flags.
        ws_registry: Socket.IO registry for streaming events to clients.
    """
    router = APIRouter()

    @router.post("/api/chat/send")
    async def send_chat_message(
        request: Request,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        """Accept a chat message via HTTP POST (guaranteed delivery).

        Creates a background task and returns immediately with the task_id.
        Streaming events are sent to the client's socket connection identified
        by the socket_id field in the request body.
        """
        if not ws_registry:
            return api_error("Chat streaming not available", 503)

        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError) as e:
            return api_error(f"Invalid JSON: {e}")

        message = payload.get("message", "")
        socket_id = payload.get("socket_id")

        if not isinstance(message, str) or not message.strip():
            return api_error("message is required")
        if not isinstance(socket_id, str) or not socket_id.strip():
            return api_error("socket_id is required")

        # Delegate to the same handler that the socket event uses.
        # This guarantees identical behaviour — the only difference is
        # message delivery is now via HTTP (reliable) instead of socket
        # (fire-and-forget).
        from ..ws_chat import handle_ws_chat
        await asyncio.to_thread(
            handle_ws_chat,
            ws_registry,
            conn_id=socket_id,
            conversation_store=conversation_store,
            repo_root=repo_root,
            workflow_store=workflow_store,
            user_id=user.id,
            payload=payload,
            conversation_logger=conversation_logger,
        )

        return JSONResponse({
            "ok": True,
            "task_id": payload.get("task_id"),
            "current_workflow_id": payload.get("current_workflow_id"),
        })

    @router.post("/api/chat")
    async def chat(
        request: Request,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError) as e:
            return api_error(f"Invalid JSON: {e}")

        message = payload.get("message", "")
        conversation_id = payload.get("conversation_id")
        image_data = payload.get("image")

        if not isinstance(message, str) or not message.strip():
            return api_error("message is required")

        convo = conversation_store.get_or_create(conversation_id)
        if isinstance(image_data, str) and image_data.strip():
            try:
                save_uploaded_image(image_data, repo_root=repo_root)
            except Exception as exc:
                logger.exception("Failed to save uploaded image")
                return api_error(f"Invalid image data: {exc}")

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
        # Try in-memory store first (richest data).
        # Only use it when the orchestrator history is non-empty — during
        # mid-task execution the history hasn't been saved yet, so fall
        # through to the persistent ConversationLogger instead.
        convo = conversation_store.get(conversation_id)
        if convo and convo.orchestrator.conversation.history:
            # Build a lookup of tool_calls per assistant response from
            # the audit trail so we can attach them to messages.  The
            # in-memory history only has plain text; the conversation
            # logger has the structured tool_call entries.
            assistant_tool_calls: Dict[int, list] = {}
            if conversation_logger:
                entries = conversation_logger.get_conversation_timeline(
                    conversation_id,
                    entry_types=["user_message", "assistant_response", "tool_call"],
                )
                pending_tools: list[dict] = []
                assistant_seq = 0  # counts assistant msgs seen
                for entry in entries:
                    etype = entry["entry_type"]
                    if etype == "tool_call":
                        pending_tools.append({
                            "tool": entry.get("tool_name", ""),
                            "arguments": {},
                            "success": bool(entry.get("tool_success", 1)),
                        })
                    elif etype == "user_message":
                        pending_tools = []
                    elif etype == "assistant_response":
                        if pending_tools:
                            assistant_tool_calls[assistant_seq] = pending_tools
                            pending_tools = []
                        assistant_seq += 1

            messages = []
            assistant_idx = 0
            for idx, msg in enumerate(convo.orchestrator.conversation.history):
                role = msg.get("role", "assistant")
                content = msg.get("content", "")
                tool_calls = []
                if role == "assistant":
                    tool_calls = assistant_tool_calls.get(assistant_idx, [])
                    assistant_idx += 1
                messages.append(
                    {
                        "id": f"{conversation_id}_{idx}",
                        "role": role,
                        "content": content,
                        "timestamp": utc_now(),
                        "tool_calls": tool_calls,
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

        return api_error("conversation not found", 404)

    app.include_router(router)
