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

    Queue is unbounded by default (suitable for chat streams which can produce
    thousands of events). Pass maxsize to the constructor to cap it for
    bounded-event use cases like stepped execution.
    """

    def __init__(self, maxsize: int = 0) -> None:
        # maxsize=0 means unbounded (Python queue.Queue default)
        self._queue: queue.Queue[Optional[Tuple[str, Dict[str, Any]]]] = queue.Queue(
            maxsize=maxsize
        )
        self._maxsize = maxsize
        self._closed = False

    def push(self, event: str, data: Dict[str, Any]) -> None:
        """Push an event to the stream.

        No-ops if sink is closed. If the queue has a size limit and is full,
        the event is dropped with a warning log.
        """
        if self._closed:
            return
        try:
            self._queue.put_nowait((event, data))
        except queue.Full:
            logger.warning("EventSink queue full (%d), dropping event: %s", self._maxsize, event)

    def close(self) -> None:
        """Close the stream. Sends a sentinel so the iterator stops yielding.

        Uses put with a short timeout to avoid deadlocking if the client has
        disconnected and the iterator is no longer draining the queue.
        """
        if not self._closed:
            self._closed = True
            try:
                self._queue.put(None, timeout=5.0)
            except queue.Full:
                # Queue is full and iterator is dead — nothing we can do.
                # The iterator will detect _closed on next wakeup.
                logger.warning("EventSink.close(): queue full, sentinel not delivered")

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
                    # Check if closed while we were waiting
                    if self._closed:
                        break
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
