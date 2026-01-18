"""Socket handlers for the API server."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from flask import request
from flask_socketio import SocketIO

from .conversations import ConversationStore
from .socket_chat import handle_socket_chat

logger = logging.getLogger("backend.api")


def register_socket_handlers(
    socketio: SocketIO,
    *,
    conversation_store: ConversationStore,
    repo_root: Path,
) -> None:
    @socketio.on("connect")
    def socket_connect() -> None:
        session_id = request.args.get("session_id")
        logger.info("Socket connected session_id=%s sid=%s", session_id, request.sid)

    @socketio.on("disconnect")
    def socket_disconnect() -> None:
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
