#!/usr/bin/env python3
"""Run the LEMON MCP server."""

import os

os.environ.setdefault("LEMON_LOG_PREFIX", "mcp")

from src.backend.mcp_bridge.server import main

if __name__ == "__main__":
    main()
