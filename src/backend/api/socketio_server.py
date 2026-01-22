"""Socket.IO factory for the API server."""

from __future__ import annotations

from flask import Flask
from flask_socketio import SocketIO

from .common import cors_origins


def create_socketio(app: Flask) -> SocketIO:
    return SocketIO(
        app,
        cors_allowed_origins=cors_origins(),
        logger=True,
        engineio_logger=True,
        max_http_buffer_size=10 * 1024 * 1024,
        async_mode="threading",
    )
