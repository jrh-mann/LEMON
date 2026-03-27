"""Shared execution-specific exceptions."""


class StoppedExecutionError(Exception):
    """Raised when workflow execution is stopped by the user."""
