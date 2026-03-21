"""FastAPI app factory for the API server."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address

from ..utils.logging import setup_logging
from .common import cors_origins

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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app
