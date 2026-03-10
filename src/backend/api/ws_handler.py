"""Socket.IO event handlers with auth and dispatch.

Replaces the old raw WebSocket endpoint. All client<->server communication
uses python-socketio events instead of JSON {type, payload} messages.

Auth: The client passes the session cookie in the Socket.IO handshake
(cookies are sent automatically by the browser for same-origin, or
via the `auth` option for cross-origin). We validate the cookie in the
connect handler and reject unauthenticated connections.
"""

from __future__ import annotations

import asyncio
import logging
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any, Dict

import socketio

from .auth import get_session_from_cookies
from .conversations import ConversationStore
from .ws_registry import ConnectionRegistry
from ..storage.auth import AuthStore
from ..storage.conversation_log import ConversationLogger
from ..storage.workflows import WorkflowStore

logger = logging.getLogger("backend.api")

# Module-level socketio server -- created once, imported by api_server.py
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=[],  # CORS handled by FastAPI middleware; SIO trusts all
    logger=False,             # Use our own logger, not engineio's verbose one
    engineio_logger=False,
)


def create_registry() -> ConnectionRegistry:
    """Create a ConnectionRegistry wrapping the module-level sio server."""
    return ConnectionRegistry(sio)


def register_sio_events(
    *,
    ws_registry: ConnectionRegistry,
    conversation_store: ConversationStore,
    repo_root: Path,
    auth_store: AuthStore,
    workflow_store: WorkflowStore,
    conversation_logger: ConversationLogger,
) -> None:
    """Register all Socket.IO event handlers.

    Called once at startup from api_server.py after the registry is created.
    Each @sio.event replaces a branch in the old WebSocket dispatch loop.
    """

    @sio.event
    async def connect(sid: str, environ: dict, auth: dict | None = None) -> bool | None:
        """Authenticate on connect via session cookie.

        Socket.IO sends cookies automatically for same-origin connections.
        For cross-origin, the client can pass auth data in the handshake.
        Returns False to reject the connection.
        """
        # Parse cookies from the HTTP headers in the WSGI environ
        cookie_header = environ.get("HTTP_COOKIE", "")
        cookies: Dict[str, str] = {}
        if cookie_header:
            sc = SimpleCookie(cookie_header)
            cookies = {k: v.value for k, v in sc.items()}

        session_info = get_session_from_cookies(auth_store, cookies)
        if not session_info:
            logger.warning("SIO connect rejected: no valid session sid=%s", sid)
            return False  # Reject connection

        _session, user = session_info
        # Store user info on the socketio session and our registry
        await sio.save_session(sid, {"user_id": user.id})
        ws_registry.set_user(sid, user.id)
        logger.info("SIO connected user_id=%s sid=%s", user.id, sid)
        # Emit connected event so client knows its sid
        await sio.emit("connected", {"sid": sid}, to=sid)

    @sio.event
    async def disconnect(sid: str) -> None:
        """Clean up on disconnect."""
        ws_registry.remove_user(sid)
        logger.info("SIO disconnected sid=%s", sid)

    # -- Chat events --

    @sio.event
    async def chat(sid: str, data: Dict[str, Any]) -> None:
        """Handle chat message from client -- spawn background task."""
        session = await sio.get_session(sid)
        user_id = session.get("user_id", "")
        from .ws_chat import handle_ws_chat
        await asyncio.to_thread(
            handle_ws_chat,
            ws_registry,
            conn_id=sid,
            conversation_store=conversation_store,
            repo_root=repo_root,
            workflow_store=workflow_store,
            user_id=user_id,
            payload=data,
            conversation_logger=conversation_logger,
        )

    @sio.event
    async def cancel_task(sid: str, data: Dict[str, Any]) -> None:
        """Handle task cancellation."""
        from .ws_chat import handle_cancel_task
        await asyncio.to_thread(
            handle_cancel_task, ws_registry, conn_id=sid, payload=data,
        )

    @sio.event
    async def sync_workflow(sid: str, data: Dict[str, Any]) -> None:
        """Handle full workflow sync from frontend."""
        from .ws_chat import handle_sync_workflow
        await asyncio.to_thread(
            handle_sync_workflow,
            ws_registry,
            conversation_store=conversation_store,
            payload=data,
        )

    @sio.event
    async def resume_task(sid: str, data: Dict[str, Any]) -> None:
        """Reconnect a refreshed frontend to a running backend task."""
        session = await sio.get_session(sid)
        user_id = session.get("user_id", "")
        from .ws_chat import handle_resume_task
        await asyncio.to_thread(
            handle_resume_task,
            ws_registry,
            conn_id=sid,
            user_id=user_id,
            payload=data,
        )

    # -- Execution events --

    @sio.event
    async def execute_workflow(sid: str, data: Dict[str, Any]) -> None:
        """Start stepped workflow execution."""
        session = await sio.get_session(sid)
        user_id = session.get("user_id", "")
        from .ws_execution import handle_execute_workflow
        await asyncio.to_thread(
            handle_execute_workflow,
            ws_registry,
            conn_id=sid,
            workflow_store=workflow_store,
            user_id=user_id,
            payload=data,
        )

    @sio.event
    async def pause_execution(sid: str, data: Dict[str, Any]) -> None:
        """Pause a running execution."""
        from .ws_execution import handle_pause_execution
        await asyncio.to_thread(handle_pause_execution, payload=data)

    @sio.event
    async def resume_execution(sid: str, data: Dict[str, Any]) -> None:
        """Resume a paused execution."""
        from .ws_execution import handle_resume_execution
        await asyncio.to_thread(handle_resume_execution, payload=data)

    @sio.event
    async def stop_execution(sid: str, data: Dict[str, Any]) -> None:
        """Stop a running execution."""
        from .ws_execution import handle_stop_execution
        await asyncio.to_thread(handle_stop_execution, payload=data)
