"""WebSocket connection registry.

Tracks active WebSocket connections and provides helpers for sending
messages from both async and sync (background thread) contexts.

Background threads (SocketChatTask, SteppedExecutionTask, BackgroundBuilderCallbacks)
run synchronous code but need to send to async WebSocket. This class bridges
the gap with asyncio.run_coroutine_threadsafe().

The event loop is set lazily via set_loop() — called from FastAPI's lifespan
startup hook, NOT at import time.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Dict, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionRegistry:
    """Track active WebSocket connections and provide send helpers."""

    def __init__(self) -> None:
        # Event loop set lazily via set_loop() from FastAPI lifespan
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # conn_id → (WebSocket, user_id) — user_id stored for ownership checks on reconnect
        self._connections: Dict[str, tuple[WebSocket, str]] = {}
        self._lock = threading.Lock()

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Called once from the FastAPI lifespan startup event."""
        self._loop = loop

    def register(self, conn_id: str, ws: WebSocket, user_id: str) -> None:
        """Register a new WebSocket connection with owner user_id."""
        with self._lock:
            self._connections[conn_id] = (ws, user_id)

    def unregister(self, conn_id: str) -> None:
        """Remove a connection from the registry."""
        with self._lock:
            self._connections.pop(conn_id, None)

    def has(self, conn_id: str) -> bool:
        """Check if a conn_id is currently registered."""
        with self._lock:
            return conn_id in self._connections

    def get_user_id(self, conn_id: str) -> Optional[str]:
        """Return the user_id that owns this conn_id, or None if not found."""
        with self._lock:
            entry = self._connections.get(conn_id)
            return entry[1] if entry else None

    def rebind(self, conn_id: str, ws: WebSocket) -> None:
        """Rebind a conn_id to a new WebSocket (reconnection).

        Preserves the original user_id ownership.
        """
        with self._lock:
            entry = self._connections.get(conn_id)
            if entry:
                self._connections[conn_id] = (ws, entry[1])

    async def send_to(self, conn_id: str, event: str, payload: dict) -> None:
        """Send JSON message to a specific connection (async context)."""
        with self._lock:
            entry = self._connections.get(conn_id)
        ws = entry[0] if entry else None
        if ws:
            try:
                await ws.send_json({"type": event, "payload": payload})
            except Exception as exc:
                logger.warning("send_to failed for conn_id=%s event=%s: %s", conn_id, event, exc)

    def send_to_sync(self, conn_id: str, event: str, payload: dict) -> None:
        """Send from a background thread (sync context).

        Uses asyncio.run_coroutine_threadsafe() to dispatch to the event loop.
        Short timeout + swallowed exceptions so a dead connection doesn't
        stall the streaming hot path.
        """
        if not self._loop:
            return
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.send_to(conn_id, event, payload),
                self._loop,
            )
            future.result(timeout=0.5)  # Short timeout for streaming hot path
        except Exception as exc:
            logger.warning("send_to_sync failed for conn_id=%s event=%s: %s", conn_id, event, exc)

    def sleep_sync(self, seconds: float) -> None:
        """Non-blocking sleep from background thread (replaces socketio.sleep)."""
        time.sleep(seconds)
