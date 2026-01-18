"""Flask app factory for the API server."""

from __future__ import annotations

from flask import Flask
from flask_cors import CORS

from ..logging_utils import setup_logging


def create_app() -> Flask:
    setup_logging()
    app = Flask(__name__)
    CORS(app)
    return app
