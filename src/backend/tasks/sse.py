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
import time
from typing import Any, Dict, Iterator, Optional, Tuple

logger = logging.getLogger(__name__)

# SSE keepalive interval — prevents reverse proxies from timing out idle connections.
# Shorter than typical proxy timeouts (60-120s) to be safe.
_KEEPALIVE_INTERVAL_SECONDS = 15

# Module-level counter for unique sink IDs (debug logging)
_sink_counter = 0


class EventSink:
    """Thread-safe event queue for SSE streaming.

    Background threads push (event_name, data_dict) tuples.
    FastAPI's StreamingResponse iterates over SSE-formatted lines.
    Closing the sink (or client disconnect) signals the end of the stream.
    """

    def __init__(self) -> None:
        global _sink_counter
        _sink_counter += 1
        self._id = _sink_counter
        self._queue: queue.Queue[Optional[Tuple[str, Dict[str, Any]]]] = queue.Queue()
        self._closed = False
        self._event_count = 0
        self._keepalive_count = 0
        self._created_at = time.monotonic()
        logger.info("EventSink[%d] created", self._id)

    def push(self, event: str, data: Dict[str, Any]) -> None:
        """Push an event to the stream. No-ops silently if sink is closed."""
        if not self._closed:
            self._event_count += 1
            self._queue.put((event, data))
        else:
            if self._event_count < 500:  # Don't spam logs for long-dead sinks
                logger.debug("EventSink[%d] push(%s) dropped — sink closed", self._id, event)

    def close(self) -> None:
        """Close the stream. Sends a sentinel so the iterator stops yielding."""
        if not self._closed:
            elapsed = time.monotonic() - self._created_at
            logger.info(
                "EventSink[%d] closing after %.1fs — %d events, %d keepalives",
                self._id, elapsed, self._event_count, self._keepalive_count,
            )
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
        logger.info("EventSink[%d] iterator started", self._id)
        try:
            while True:
                try:
                    item = self._queue.get(timeout=_KEEPALIVE_INTERVAL_SECONDS)
                except queue.Empty:
                    # Yield SSE comment as keepalive (keeps proxies happy)
                    self._keepalive_count += 1
                    if self._keepalive_count <= 3 or self._keepalive_count % 20 == 0:
                        logger.debug(
                            "EventSink[%d] keepalive #%d (events so far: %d)",
                            self._id, self._keepalive_count, self._event_count,
                        )
                    yield ": keepalive\n\n"
                    continue

                if item is None:
                    # Sentinel — stream is done
                    elapsed = time.monotonic() - self._created_at
                    logger.info(
                        "EventSink[%d] sentinel received — stream done after %.1fs",
                        self._id, elapsed,
                    )
                    break

                event, data = item
                yield f"event: {event}\ndata: {json.dumps(data)}\n\n"

        except GeneratorExit:
            # Client disconnected — mark sink closed so the background task
            # can detect this via sink.is_closed and stop doing work.
            elapsed = time.monotonic() - self._created_at
            logger.warning(
                "EventSink[%d] GeneratorExit (client disconnected) after %.1fs — %d events, %d keepalives",
                self._id, elapsed, self._event_count, self._keepalive_count,
            )
            self._closed = True
