"""Flask app factory for the API server."""

from __future__ import annotations

from flask import Flask
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from ..utils.logging import setup_logging
from .common import cors_origins

# Rate limiter instance - 60 requests/minute per IP for HTTP endpoints
# Note: WebSocket traffic (chat, sync_workflow) is not affected by this limiter
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["60 per minute"],
    storage_uri="memory://",
)


def create_app() -> Flask:
    setup_logging()
    app = Flask(__name__)
    CORS(app, supports_credentials=True, origins=cors_origins())
    limiter.init_app(app)
    return app
