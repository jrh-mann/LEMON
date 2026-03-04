#!/usr/bin/env python3
"""Run the LEMON API server with uvicorn."""

import os

os.environ.setdefault("LEMON_LOG_PREFIX", "backend")

from src.backend.api_server import app  # noqa: E402

if __name__ == "__main__":
    import uvicorn

    debug = os.environ.get("LEMON_DEBUG", "1").lower() in {"1", "true", "yes"}
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=5001,
        log_level="debug" if debug else "info",
    )
