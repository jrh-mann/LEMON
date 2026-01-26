"""Socket handlers for the API server."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from flask import request
from flask_socketio import SocketIO

from .conversations import ConversationStore
from .auth import get_session_from_request
from ..storage.auth import AuthStore
from ..storage.workflows import WorkflowStore
from .socket_chat import handle_cancel_task, handle_socket_chat, handle_sync_workflow

logger = logging.getLogger("backend.api")


def register_socket_handlers(
    socketio: SocketIO,
    *,
    conversation_store: ConversationStore,
    repo_root: Path,
    auth_store: AuthStore,
    workflow_store: WorkflowStore,
) -> None:
    @socketio.on("connect")
    def socket_connect(auth: Any = None) -> None:
        session = get_session_from_request(auth_store)
        if not session:
            logger.warning("Socket rejected unauthenticated sid=%s", request.sid)
            return False
        _, user = session
        session_id = request.args.get("session_id")
        logger.info("Socket connected user_id=%s session_id=%s sid=%s", user.id, session_id, request.sid)

    @socketio.on("disconnect")
    def socket_disconnect(reason: Any = None) -> None:
        if reason:
            logger.info("Socket disconnected sid=%s reason=%s", request.sid, reason)
        else:
            logger.info("Socket disconnected sid=%s", request.sid)

    @socketio.on_error_default  # type: ignore[misc]
    def default_socket_error(exc: Exception) -> None:
        logger.exception("Socket error: %s", exc)

    @socketio.on("connect_error")
    def socket_connect_error(data: Any) -> None:
        logger.error("Socket connect_error data=%s", data)

    @socketio.on("chat")
    def socket_chat(payload: Dict[str, Any]) -> None:
        handle_socket_chat(
            socketio,
            conversation_store=conversation_store,
            repo_root=repo_root,
            payload=payload,
        )

    @socketio.on("sync_workflow")
    def socket_sync_workflow(payload: Dict[str, Any]) -> None:
        handle_sync_workflow(
            socketio,
            conversation_store=conversation_store,
            payload=payload,
        )

    @socketio.on("cancel_task")
    def socket_cancel_task(payload: Dict[str, Any]) -> None:
        handle_cancel_task(socketio, payload=payload)
