"""Socket.IO-backed connection registry.

Wraps a python-socketio AsyncServer instance and provides helpers for
sending events from both async and sync (background thread) contexts.

Background threads (WsChatTask, SteppedExecutionTask, BackgroundBuilderCallbacks)
run synchronous code but need to emit via the async Socket.IO server.
The send_to_sync() method bridges the gap with asyncio.run_coroutine_threadsafe().

The event loop is set lazily via set_loop() -- called from FastAPI's lifespan
startup hook, NOT at import time.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Optional

import socketio

logger = logging.getLogger(__name__)


class ConnectionRegistry:
    """Wrap a python-socketio AsyncServer with sync emit helpers.

    Provides the same send_to_sync() / sleep_sync() interface that
    WsChatTask, SteppedExecutionTask, and BackgroundBuilderCallbacks
    rely on, but delegates to socketio.AsyncServer under the hood.
    """

    def __init__(self, sio: socketio.AsyncServer) -> None:
        # The shared AsyncServer instance created in ws_handler.py
        self.sio = sio
        # Event loop set lazily via set_loop() from FastAPI lifespan
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # sid -> user_id mapping for ownership checks on reconnect
        self._user_map: dict[str, str] = {}
        self._lock = threading.Lock()

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Called once from the FastAPI lifespan startup event."""
        self._loop = loop

    # -- User tracking (replaces old conn_id -> (ws, user_id) map) --

    def set_user(self, sid: str, user_id: str) -> None:
        """Record which user owns a given socket session."""
        with self._lock:
            self._user_map[sid] = user_id

    def get_user_id(self, sid: str) -> Optional[str]:
        """Return the user_id that owns this sid, or None."""
        with self._lock:
            return self._user_map.get(sid)

    def remove_user(self, sid: str) -> None:
        """Remove a sid from the user map (on disconnect)."""
        with self._lock:
            self._user_map.pop(sid, None)

    # -- Emit helpers --

    async def send_to(self, sid: str, event: str, payload: dict) -> None:
        """Emit an event to a specific client (async context)."""
        try:
            await self.sio.emit(event, payload, to=sid)
        except Exception as exc:
            logger.warning("send_to failed for sid=%s event=%s: %s", sid, event, exc)

    def send_to_sync(self, sid: str, event: str, payload: dict) -> None:
        """Emit from a background thread (sync context).

        Uses asyncio.run_coroutine_threadsafe() to dispatch to the event loop.
        Short timeout + swallowed exceptions so a dead connection doesn't
        stall the streaming hot path.
        """
        if not self._loop:
            return
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.sio.emit(event, payload, to=sid),
                self._loop,
            )
            future.result(timeout=0.5)  # Short timeout for streaming hot path
        except Exception as exc:
            logger.warning("send_to_sync failed for sid=%s event=%s: %s", sid, event, exc)

    def sleep_sync(self, seconds: float) -> None:
        """Non-blocking sleep from background thread."""
        time.sleep(seconds)
