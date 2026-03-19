"""FastAPI app factory for the API server."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse

from ..utils.logging import setup_logging
from .common import cors_origins

# Maximum request body size: 10 MB (generous for image uploads)
_MAX_BODY_BYTES = 10 * 1024 * 1024

# Rate limiter instance — 60 requests/minute per IP for HTTP endpoints.
# WebSocket traffic (chat, sync_workflow) is not affected by this limiter.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["60/minute"],
)


def create_app(**kwargs: Any) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        **kwargs: Passed through to FastAPI() constructor (e.g. lifespan).
    """
    setup_logging()
    app = FastAPI(**kwargs)
    app.state.limiter = limiter
    app.add_exception_handler(
        RateLimitExceeded,
        lambda request, exc: JSONResponse(
            {"error": f"Rate limit exceeded: {exc.detail}"},
            status_code=429,
        ),
    )
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        """Attach defense-in-depth security headers to every response."""
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "script-src 'self'"
        )
        return response

    @app.middleware("http")
    async def limit_request_size(request: Request, call_next):
        """Reject requests with bodies larger than _MAX_BODY_BYTES."""
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > _MAX_BODY_BYTES:
            return JSONResponse(
                {"error": "Request too large"},
                status_code=413,
            )
        return await call_next(request)

    return app
