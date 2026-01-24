#!/usr/bin/env bash
set -euo pipefail

: "${MCP_HOST:=127.0.0.1}"
: "${MCP_PORT:=8001}"
: "${MCP_TRANSPORT:=streamable-http}"
: "${PORT:=8000}"

export MCP_HOST MCP_PORT MCP_TRANSPORT

if [ -z "${LEMON_MCP_URL:-}" ]; then
  export LEMON_MCP_URL="http://127.0.0.1:${MCP_PORT}/mcp"
fi

python run_mcp.py &

exec gunicorn --bind=0.0.0.0:"${PORT}" --timeout 600 src.backend.api_server:app
