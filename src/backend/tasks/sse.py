"""Server-Sent Events (SSE) infrastructure.

Provides EventSink — a thread-safe queue that bridges background task threads
with FastAPI's StreamingResponse. The background thread pushes events via
sink.push(), and FastAPI yields SSE-formatted lines via iteration.

Each task (ChatTask, BuilderTask) owns its own EventSink. No sharing between
tasks — this keeps lifecycle management simple (creator closes when done).
"""

from __future__ import annotations

import json
import logging
import queue
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

    def push(self, event: str, data: Dict[str, Any]) -> None:
        """Push an event to the stream. No-ops silently if sink is closed."""
        if not self._closed:
            self._queue.put((event, data))

    def close(self) -> None:
        """Close the stream. Sends a sentinel so the iterator stops yielding."""
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
