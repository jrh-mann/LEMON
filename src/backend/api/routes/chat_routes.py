"""Chat routes: SSE streaming, cancel, resume, and conversation history.

POST /api/chat/send  — returns an SSE stream for one chat turn
POST /api/chat/cancel — cancel an in-progress task
POST /api/chat/resume — re-attach to a running task (returns SSE stream)
GET  /api/chat/<id>   — retrieve conversation history
POST /api/chat        — legacy sync endpoint (no streaming)
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Request
from starlette.responses import JSONResponse, StreamingResponse

from ..common import utc_now
from ...tasks.conversations import ConversationStore
from ...tasks.chat_task import ChatTask
from ..deps import require_auth
from ..response_utils import extract_flowchart, extract_tool_calls, summarize_response
from ...tasks.sse import EventSink
from ...tasks.registry import task_registry
from ...agents.turn import Turn
from ...storage.auth import AuthUser
from ...storage.conversation_log import ConversationLogger
from ...storage.workflows import WorkflowStore
from ...utils.uploads import save_uploaded_image
from ...workflow_persistence import persist_workflow_snapshot
from .helpers import api_error

logger = logging.getLogger("backend.api")


def register_chat_routes(
    app: FastAPI,
    *,
    conversation_store: ConversationStore,
    repo_root: Path,
    conversation_logger: Optional[ConversationLogger] = None,
    workflow_store: Optional[WorkflowStore] = None,
) -> None:
    """Register chat endpoints on the FastAPI app.

    Args:
        app: FastAPI application instance.
        conversation_store: In-memory conversation manager.
        repo_root: Repository root path for image uploads.
        conversation_logger: SQLite audit log for persistent chat history.
        workflow_store: Workflow store for setting building flags.
    """
    router = APIRouter()

    @router.post("/api/chat/send")
    async def send_chat_message(
        request: Request,
        user: AuthUser = Depends(require_auth),
    ) -> StreamingResponse:
        """Accept a chat message and return an SSE stream for the response.

        The HTTP response IS the stream — events are yielded as SSE lines
        until the LLM finishes responding over SSE.
        """
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError) as e:
            return api_error(f"Invalid JSON: {e}")

        message = payload.get("message", "")
        if not isinstance(message, str) or not message.strip():
            return api_error("message is required")

        task_id = payload.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            task_id = uuid4().hex

        current_workflow_id = payload.get("current_workflow_id") or f"wf_{uuid4().hex}"

        # Create the SSE event sink — the task pushes events, we yield them
        sink = EventSink()

        task = ChatTask(
            sink=sink,
            conversation_store=conversation_store,
            repo_root=repo_root,
            workflow_store=workflow_store,
            user_id=user.id,
            task_id=task_id,
            message=message,
            conversation_id=payload.get("conversation_id"),
            files_data=payload.get("files") or [],
            workflow=payload.get("workflow"),
            analysis=payload.get("analysis"),
            current_workflow_id=current_workflow_id,
            open_tabs=payload.get("open_tabs"),
            img_annotations=payload.get("annotations"),
            conversation_logger=conversation_logger,
        )

        # Register and set building=True BEFORE spawning the thread.
        # Eliminates the race where a page refresh between thread spawn
        # and thread execution finds building=false and no active task.
        task_registry.register(task)
        if workflow_store and current_workflow_id:
            try:
                workflow_data = payload.get("workflow") or {}
                persist_workflow_snapshot(
                    workflow_store,
                    workflow_id=current_workflow_id,
                    user_id=user.id,
                    name="New Workflow",
                    description="",
                    nodes=workflow_data.get("nodes", []),
                    edges=workflow_data.get("edges", []),
                    variables=workflow_data.get("variables", []),
                    outputs=workflow_data.get("outputs"),
                    output_type=workflow_data.get("output_type"),
                    is_draft=True,
                )
                workflow_store.update_workflow(current_workflow_id, user.id, building=True)
            except Exception:
                logger.error(
                    "Failed to set building=True for %s before thread spawn",
                    current_workflow_id, exc_info=True,
                )

        # Spawn background thread — it pushes events to the sink
        threading.Thread(
            target=task.run, daemon=True, name=f"chat-{task_id}",
        ).start()

        # Return the sink as an SSE stream — the HTTP response stays open
        # until task.run() calls sink.close() or the client disconnects
        return StreamingResponse(
            sink,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )

    @router.post("/api/chat/cancel")
    async def cancel_chat_task(
        request: Request,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        """Cancel an in-progress chat task."""
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError) as e:
            return api_error(f"Invalid JSON: {e}")

        task_id = payload.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            return api_error("task_id is required")

        task = task_registry.cancel(task_id)
        if task and task_registry.mark_notified(task_id):
            # Push cancellation event to the task's SSE stream
            cancel_payload: Dict[str, Any] = {"task_id": task_id}
            if task.current_workflow_id:
                cancel_payload["workflow_id"] = task.current_workflow_id
            task.sink.push("chat_cancelled", cancel_payload)

        return JSONResponse({"ok": True})

    @router.post("/api/chat/resume", response_model=None)
    async def resume_chat_task(
        request: Request,
        user: AuthUser = Depends(require_auth),
    ) -> StreamingResponse | JSONResponse:
        """Re-attach to a running task after page refresh.

        If a task is still running for the given workflow, creates a new
        EventSink, swaps it into the task (replaying accumulated content),
        and returns an SSE stream. If no active task, returns JSON.
        """
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError) as e:
            return api_error(f"Invalid JSON: {e}")

        workflow_id = payload.get("workflow_id")
        if not workflow_id:
            return api_error("workflow_id is required")

        task = task_registry.get_by_workflow(user.id, workflow_id)

        if task and not task.done.is_set():
            # Create a new sink, swap it into the running task
            new_sink = EventSink()
            task.swap_sink(new_sink)
            logger.info(
                "resume: reconnected workflow=%s task=%s "
                "replay_thinking=%d replay_stream=%d",
                workflow_id, task.task_id,
                len("".join(task.thinking_chunks)), len(task.stream_buffer),
            )
            return StreamingResponse(
                new_sink,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        else:
            # Task already finished — tell the frontend to fetch conversation history
            logger.info(
                "resume: no active task for workflow=%s, sending no_active_task",
                workflow_id,
            )
            return JSONResponse({"status": "no_active_task", "workflow_id": workflow_id})

    @router.post("/api/chat")
    async def chat(
        request: Request,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        """Legacy sync chat endpoint (no streaming). Used by tests."""
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

        turn = Turn(message, convo.id)
        turn.start()
        try:
            response_text = convo.orchestrator.respond(
                message,
                turn=turn,
                has_files=[],
                allow_tools=True,
                on_tool_event=on_tool_event,
            )
            turn.complete(response_text)
        except Exception:
            turn.fail(str(message))
            response_text = ""
        finally:
            from ...agents.turn import TurnStatus
            if turn.status != TurnStatus.PENDING:
                turn.commit(convo.orchestrator.conversation)

        tool_calls = extract_tool_calls(response_text, include_result=False)
        if not tool_calls and turn.tool_calls:
            tool_calls = turn.tool_calls
        elif not tool_calls and executed_tools:
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
        convo = conversation_store.get(conversation_id)
        if convo and convo.orchestrator.conversation.history:
            messages = []
            pending_user: dict | None = None
            pending_assistant: dict | None = None

            for idx, msg in enumerate(convo.orchestrator.conversation.history):
                role = msg.get("role", "assistant")
                content = msg.get("content", "")

                if isinstance(content, str) and content.startswith("[CANCELLED]"):
                    continue

                # Tool result messages are user messages with tool_result
                # content blocks — skip them (internal to tool loop)
                is_tool_result = (
                    role == "user"
                    and isinstance(content, list)
                    and content
                    and isinstance(content[0], dict)
                    and content[0].get("type") == "tool_result"
                )
                if role == "user" and not is_tool_result:
                    if pending_user is not None:
                        messages.append(pending_user)
                        if pending_assistant is not None:
                            messages.append(pending_assistant)
                    pending_user = {
                        "id": f"{conversation_id}_{idx}",
                        "role": "user",
                        "content": content,
                        "timestamp": utc_now(),
                        "tool_calls": [],
                    }
                    pending_assistant = None
                elif role == "assistant":
                    tc = msg.get("tool_calls_meta", [])
                    # Keep assistant messages with content OR tool_calls_meta
                    # (ask_question can produce empty-content messages with tools)
                    if content or tc:
                        pending_assistant = {
                            "id": f"{conversation_id}_{idx}",
                            "role": "assistant",
                            "content": content,
                            "timestamp": utc_now(),
                            "tool_calls": tc,
                        }

            if pending_user is not None:
                messages.append(pending_user)
                if pending_assistant is not None:
                    messages.append(pending_assistant)
            return JSONResponse(
                {
                    "id": convo.id,
                    "messages": messages,
                    "working": {},
                    "created_at": convo.created_at,
                    "updated_at": convo.updated_at,
                }
            )

        if conversation_logger:
            entries = conversation_logger.get_conversation_timeline(
                conversation_id,
                entry_types=["user_message", "assistant_response", "tool_call"],
            )
            if entries:
                messages = []
                pending_tool_calls: list[dict] = []
                for entry in entries:
                    etype = entry["entry_type"]
                    if etype == "tool_call":
                        tool_args = entry.get("tool_arguments")
                        pending_tool_calls.append({
                            "tool": entry.get("tool_name", ""),
                            "arguments": json.loads(tool_args) if tool_args else {},
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
