"""Frontend static asset serving for the API server.

Mounts static assets at /assets and provides a SPA catch-all that
serves index.html for all non-API, non-WS paths.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse


def register_frontend_routes(app: FastAPI, frontend_dist: Path) -> None:
    """Mount frontend static files and SPA catch-all route.

    Args:
        app: FastAPI application instance.
        frontend_dist: Path to the built frontend dist directory.
    """
    if not frontend_dist.exists():
        return

    # Mount static assets directory (JS/CSS bundles, fonts, etc.)
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    # SPA catch-all — serves index.html for all non-API, non-WS paths
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> FileResponse:
        # Don't catch API or WebSocket routes
        if full_path.startswith("api/") or full_path == "ws":
            raise HTTPException(status_code=404)
        # Serve exact file if it exists (e.g. favicon.ico, robots.txt)
        candidate = frontend_dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        # Fall back to index.html for SPA client-side routing
        return FileResponse(frontend_dist / "index.html")
