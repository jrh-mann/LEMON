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

# uvicorn ASGI server for Socket.IO + FastAPI
# Use "python -m uvicorn" instead of bare "uvicorn" because Azure Oryx
# creates a venv with --copies whose shebang points to a temp build dir
# that doesn't exist at runtime (causes "bad interpreter" exit code 127).
exec python -m uvicorn src.backend.api_server:app --host=0.0.0.0 --port="${PORT}" --timeout-keep-alive=600
