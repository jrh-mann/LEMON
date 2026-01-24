"""Frontend static asset serving for the API server."""

from __future__ import annotations

from pathlib import Path

from flask import Flask, abort, send_from_directory


def register_frontend_routes(app: Flask, frontend_dist: Path) -> None:
    if not frontend_dist.exists():
        return

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_frontend(path: str):
        if path.startswith("api/") or path.startswith("socket.io"):
            abort(404)
        if path:
            candidate = frontend_dist / path
            if candidate.is_file():
                return send_from_directory(frontend_dist, path)
        return send_from_directory(frontend_dist, "index.html")
