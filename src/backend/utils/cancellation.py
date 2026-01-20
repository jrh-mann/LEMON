"""Cancellation primitives for chat tasks."""

from __future__ import annotations


class CancellationError(RuntimeError):
    """Raised when a user cancels an in-flight task."""

