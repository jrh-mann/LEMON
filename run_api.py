#!/usr/bin/env python3
"""Run the LEMON API server."""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

os.environ.setdefault("LEMON_LOG_PREFIX", "backend")

from src.backend.api_server import app, socketio

if __name__ == "__main__":
    # Use Socket.IO server so websocket events work in the web UI.
    debug = os.environ.get("LEMON_DEBUG", "1").lower() in {"1", "true", "yes"}
    socketio.run(
        app,
        debug=debug,
        port=5001,
        allow_unsafe_werkzeug=True,
        use_reloader=False,
    )
