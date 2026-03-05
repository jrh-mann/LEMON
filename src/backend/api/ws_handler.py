"""FastAPI WebSocket endpoint with origin validation, auth, and dispatch.

All client↔server messages are JSON: {type: string, payload: object}.
The dispatch loop routes incoming message types to the appropriate handler.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .auth import get_session_from_cookies
from .common import cors_origins
from .conversations import ConversationStore
from .ws_registry import ConnectionRegistry
from ..storage.auth import AuthStore
from ..storage.workflows import WorkflowStore

logger = logging.getLogger("backend.api")


def register_ws_endpoint(
    app: FastAPI,
    *,
    ws_registry: ConnectionRegistry,
    conversation_store: ConversationStore,
    repo_root: Path,
    auth_store: AuthStore,
    workflow_store: WorkflowStore,
) -> None:
    """Register the /ws WebSocket endpoint on the FastAPI app."""

    # Allowed origins for WebSocket upgrade validation (CORS doesn't cover WS)
    allowed = set(cors_origins())

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        # --- Origin validation (CORS doesn't apply to WebSocket upgrades) ---
        # If allowed is empty (no LEMON_CORS_ORIGINS configured), allow all origins
        # (development mode). When origins are configured, enforce the allowlist.
        origin = ws.headers.get("origin", "")
        if allowed and origin not in allowed:
            await ws.close(code=4003, reason="Origin not allowed")
            return

        # --- Authenticate via cookie ---
        cookies = dict(ws.cookies)
        session_info = get_session_from_cookies(auth_store, cookies)
        if not session_info:
            await ws.close(code=4001, reason="Authentication required")
            return
        _session, user = session_info

        # --- Accept and register connection ---
        await ws.accept()
        conn_id = uuid4().hex
        ws_registry.register(conn_id, ws, user.id)
        await ws.send_json({"type": "connected", "payload": {"conn_id": conn_id}})
        logger.info("WS connected user_id=%s conn_id=%s", user.id, conn_id)

        try:
            # --- Message loop (safe JSON parsing) ---
            async for raw in ws.iter_text():
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await ws.send_json({"type": "error", "payload": {"message": "Invalid JSON"}})
                    continue

                msg_type: str = msg.get("type", "")
                payload: Dict[str, Any] = msg.get("payload", {})

                # --- Reconnection handshake ---
                if msg_type == "reconnect":
                    old_conn_id = payload.get("conn_id")
                    if old_conn_id and ws_registry.has(old_conn_id):
                        # Verify ownership — prevent session hijacking by
                        # ensuring the reconnecting user owns the old conn_id
                        old_owner = ws_registry.get_user_id(old_conn_id)
                        if old_owner != user.id:
                            logger.warning(
                                "WS reconnect rejected: user %s tried to claim conn_id owned by %s",
                                user.id, old_owner,
                            )
                            await ws.send_json({"type": "error", "payload": {"message": "Not your connection"}})
                            continue
                        # Reuse the old conn_id — rebind it to the new WebSocket.
                        # The background thread still holds old_conn_id, so its
                        # send_to_sync() calls immediately reach the new socket.
                        ws_registry.unregister(conn_id)
                        conn_id = old_conn_id  # noqa: F841 — reassignment intentional
                        ws_registry.rebind(conn_id, ws)
                        await ws.send_json({"type": "reconnected", "payload": {"conn_id": conn_id}})
                        logger.info("WS reconnected conn_id=%s user_id=%s", conn_id, user.id)
                    # If old_conn_id not found (task already finished), keep the new conn_id

                elif msg_type == "chat":
                    from .ws_chat import handle_ws_chat
                    await asyncio.to_thread(
                        handle_ws_chat,
                        ws_registry,
                        conn_id=conn_id,
                        conversation_store=conversation_store,
                        repo_root=repo_root,
                        workflow_store=workflow_store,
                        user_id=user.id,
                        payload=payload,
                    )

                elif msg_type == "cancel_task":
                    from .ws_chat import handle_cancel_task
                    await asyncio.to_thread(
                        handle_cancel_task, ws_registry, conn_id=conn_id, payload=payload,
                    )

                elif msg_type == "sync_workflow":
                    from .ws_chat import handle_sync_workflow
                    await asyncio.to_thread(
                        handle_sync_workflow,
                        ws_registry,
                        conversation_store=conversation_store,
                        payload=payload,
                    )

                elif msg_type == "execute_workflow":
                    from .ws_execution import handle_execute_workflow
                    await asyncio.to_thread(
                        handle_execute_workflow,
                        ws_registry,
                        conn_id=conn_id,
                        workflow_store=workflow_store,
                        user_id=user.id,
                        payload=payload,
                    )

                elif msg_type == "pause_execution":
                    from .ws_execution import handle_pause_execution
                    await asyncio.to_thread(handle_pause_execution, payload=payload)

                elif msg_type == "resume_execution":
                    from .ws_execution import handle_resume_execution
                    await asyncio.to_thread(handle_resume_execution, payload=payload)

                elif msg_type == "stop_execution":
                    from .ws_execution import handle_stop_execution
                    await asyncio.to_thread(handle_stop_execution, payload=payload)

                else:
                    logger.warning("WS unknown message type=%s conn_id=%s", msg_type, conn_id)

        except WebSocketDisconnect:
            logger.info("WS disconnected conn_id=%s user_id=%s", conn_id, user.id)
        except Exception:
            logger.exception("WS error conn_id=%s", conn_id)
        finally:
            ws_registry.unregister(conn_id)
