"""Simple synchronous event bus for decoupling tool execution from transport.

Subscribers are called in registration order when events are emitted.
Errors in one subscriber are logged but do not prevent other subscribers
from running — the bus never lets a listener crash the emitter.
"""

import logging
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)

# Subscriber callback signature: (event_type: str, payload: dict) -> None
Subscriber = Callable[[str, Dict[str, Any]], None]


class EventBus:
    """Simple in-process event bus.

    Subscribers are called synchronously when events are emitted.
    Each subscriber receives the event type string and a payload dict.
    """

    def __init__(self) -> None:
        # Per-event-type subscriber lists
        self._subscribers: Dict[str, List[Subscriber]] = {}
        # Subscribers that receive every event regardless of type
        self._global_subscribers: List[Subscriber] = []

    def subscribe(self, event_type: str, callback: Subscriber) -> None:
        """Subscribe to a specific event type."""
        self._subscribers.setdefault(event_type, []).append(callback)

    def subscribe_all(self, callback: Subscriber) -> None:
        """Subscribe to ALL event types (useful for logging/debugging)."""
        self._global_subscribers.append(callback)

    def emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Emit an event to all matching subscribers.

        Type-specific subscribers are called first, then global subscribers.
        Exceptions in any single subscriber are caught and logged so that
        remaining subscribers still execute.
        """
        # Type-specific subscribers
        for callback in self._subscribers.get(event_type, []):
            try:
                callback(event_type, payload)
            except Exception:
                logger.error(
                    "Event subscriber error for %s", event_type, exc_info=True
                )

        # Global subscribers
        for callback in self._global_subscribers:
            try:
                callback(event_type, payload)
            except Exception:
                logger.error(
                    "Global event subscriber error for %s", event_type, exc_info=True
                )

    def clear(self) -> None:
        """Remove all subscribers."""
        self._subscribers.clear()
        self._global_subscribers.clear()
