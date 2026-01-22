"""Flask app factory for the API server."""

from __future__ import annotations

from flask import Flask
from flask_cors import CORS

from ..utils.logging import setup_logging
from .common import cors_origins


def create_app() -> Flask:
    setup_logging()
    app = Flask(__name__)
    CORS(app, supports_credentials=True, origins=cors_origins())
    return app
