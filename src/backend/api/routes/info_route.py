"""Info route: basic API metadata endpoint.

Provides the unauthenticated /api/info endpoint that returns
server name, version, and available endpoint paths.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from starlette.responses import JSONResponse


def register_info_route(app: FastAPI) -> None:
    """Register the /api/info endpoint on the FastAPI app.

    Args:
        app: FastAPI application instance.
    """
    router = APIRouter()

    @router.get("/api/info")
    async def api_info() -> JSONResponse:
        return JSONResponse(
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

    app.include_router(router)
