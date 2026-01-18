#!/usr/bin/env python3
"""Run the LEMON API server."""

import os

os.environ.setdefault("LEMON_LOG_PREFIX", "backend")

from src.backend.api_server import app, socketio

if __name__ == "__main__":
    # Use Socket.IO server so websocket events work in the web UI.
    socketio.run(
        app,
        debug=True,
        port=5001,
        allow_unsafe_werkzeug=True,
    )
