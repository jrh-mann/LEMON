#!/usr/bin/env bash
set -euo pipefail

export MCP_HOST="${MCP_HOST:-0.0.0.0}"
export MCP_PORT="${MCP_PORT:-$PORT}"

exec python run_mcp.py
