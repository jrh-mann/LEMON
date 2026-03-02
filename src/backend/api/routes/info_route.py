"""Info route: basic API metadata endpoint.

Provides the unauthenticated /api/info endpoint that returns
server name, version, and available endpoint paths.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify


def register_info_route(app: Flask) -> None:
    """Register the /api/info endpoint on the Flask app.

    Args:
        app: Flask application instance.
    """

    @app.get("/api/info")
    def api_info() -> Any:
        return jsonify(
            {
                "name": "LEMON Backend",
                "version": "0.1",
                "endpoints": {
                    "chat": "/api/chat",
                    "workflows": "/api/workflows",
                    "search": "/api/search",
                },
            }
        )
