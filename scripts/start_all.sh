#!/usr/bin/env bash
set -euo pipefail

: "${PORT:=8000}"

# uvicorn ASGI server for FastAPI
# Use "python -m uvicorn" instead of bare "uvicorn" because Azure Oryx
# creates a venv with --copies whose shebang points to a temp build dir
# that doesn't exist at runtime (causes "bad interpreter" exit code 127).
exec python -m uvicorn src.backend.api_server:app --host=0.0.0.0 --port="${PORT}" --timeout-keep-alive=600
