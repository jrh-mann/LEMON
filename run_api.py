#!/usr/bin/env python3
"""Run the LEMON API server with uvicorn."""

from dotenv import load_dotenv
load_dotenv()

import logging
import os

# Configure Python logging BEFORE any app imports so all loggers inherit it.
# Without this, backend.api / backend.llm loggers have no handler and are silent.
logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)-8s %(name)s: %(message)s",
)

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
