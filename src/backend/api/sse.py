"""Server-Sent Events (SSE) infrastructure.

Provides EventSink — a thread-safe queue that bridges background task threads
with FastAPI's StreamingResponse. The background thread pushes events via
sink.push(), and FastAPI yields SSE-formatted lines via iteration.

This replaces the Socket.IO ConnectionRegistry for chat and execution streaming.
HTTP itself handles connection lifecycle — no heartbeat, no dead connection
detection, no conn_id tracking needed.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from typing import Any, Dict, Iterator, Optional, Tuple

logger = logging.getLogger(__name__)

# SSE keepalive interval — prevents reverse proxies from timing out idle connections.
# Shorter than typical proxy timeouts (60-120s) to be safe.
_KEEPALIVE_INTERVAL_SECONDS = 15


class EventSink:
    """Thread-safe event queue for SSE streaming.

    Background threads push (event_name, data_dict) tuples.
    FastAPI's StreamingResponse iterates over SSE-formatted lines.
    Closing the sink (or client disconnect) signals the end of the stream.
    """

    def __init__(self) -> None:
        self._queue: queue.Queue[Optional[Tuple[str, Dict[str, Any]]]] = queue.Queue()
        self._closed = False
        # Reference counting: the creator is the initial owner (ref_count=1).
        # Background producers (subworkflow builders) call acquire() to keep
        # the SSE stream alive after the parent ChatTask finishes.
        self._ref_count = 1
        self._ref_lock = threading.Lock()

    def acquire(self) -> None:
        """Add a producer reference — prevents close until all producers release.

        Called by background builder threads that share this sink with the
        parent ChatTask. Keeps the SSE stream alive after the parent finishes.
        """
        with self._ref_lock:
            self._ref_count += 1

    def release(self) -> None:
        """Remove a producer reference — closes the sink when the last one releases.

        The parent ChatTask calls this instead of close() so that background
        builders sharing the sink can continue emitting events.
        """
        with self._ref_lock:
            self._ref_count -= 1
            should_close = self._ref_count <= 0
        if should_close:
            self.close()

    def push(self, event: str, data: Dict[str, Any]) -> None:
        """Push an event to the stream. No-ops silently if sink is closed."""
        if not self._closed:
            self._queue.put((event, data))

    def close(self) -> None:
        """Force-close the stream regardless of ref count.

        Used by swap_sink (resume after refresh) to terminate the old stream.
        For normal completion, use release() instead.
        """
        if not self._closed:
            self._closed = True
            self._queue.put(None)  # sentinel

    @property
    def is_closed(self) -> bool:
        """True after close() has been called or client disconnected."""
        return self._closed

    def __iter__(self) -> Iterator[str]:
        """Yield SSE-formatted strings until close() is called.

        Starlette runs sync iterators in a threadpool, so blocking on
        queue.get() is safe — it won't stall the event loop.
        """
        try:
            while True:
                try:
                    item = self._queue.get(timeout=_KEEPALIVE_INTERVAL_SECONDS)
                except queue.Empty:
                    # Yield SSE comment as keepalive (keeps proxies happy)
                    yield ": keepalive\n\n"
                    continue

                if item is None:
                    # Sentinel — stream is done
                    break

                event, data = item
                yield f"event: {event}\ndata: {json.dumps(data)}\n\n"

        except GeneratorExit:
            # Client disconnected — mark sink closed so the background task
            # can detect this via sink.is_closed and stop doing work.
            self._closed = True
