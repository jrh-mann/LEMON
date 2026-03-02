"""Before-request middleware for logging and authentication.

Registers Flask before_request hooks that run before every
API request to log access and enforce authentication.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask, jsonify, request, g

from ..auth import get_session_from_request
from ...storage.auth import AuthStore

logger = logging.getLogger("backend.api")

# Paths that do not require authentication
PUBLIC_PATHS = {
    "/api/info",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/register",
}


def register_middleware(app: Flask, *, auth_store: AuthStore) -> None:
    """Register before_request hooks for logging and auth enforcement.

    Args:
        app: Flask application instance.
        auth_store: Auth store for session validation.
    """

    @app.before_request
    def log_request() -> None:
        logger.info(
            "HTTP %s %s from %s",
            request.method,
            request.path,
            request.remote_addr,
        )

    @app.before_request
    def enforce_auth() -> Any:
        if request.method == "OPTIONS":
            return None
        if not request.path.startswith("/api/"):
            return None
        if request.path in PUBLIC_PATHS:
            return None
        session_info = get_session_from_request(auth_store)
        if not session_info:
            return jsonify({"error": "Authentication required."}), 401
        session, user = session_info
        g.auth_session = session
        g.auth_user = user
        return None
