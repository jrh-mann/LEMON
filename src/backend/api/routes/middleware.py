"""Request logging middleware.

Auth enforcement is handled by FastAPI Depends() in each route — this
middleware only logs incoming HTTP requests for observability.
"""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("backend.api")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every incoming HTTP request method, path, and client IP."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        logger.info(
            "HTTP %s %s from %s",
            request.method,
            request.url.path,
            request.client.host if request.client else "unknown",
        )
        return await call_next(request)
