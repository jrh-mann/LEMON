#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

start_process() {
  local name="$1"
  shift
  echo "Starting ${name}..."
  "$@" &
  local pid=$!
  PIDS+=("${pid}")
  echo "${name} pid=${pid}"
}

cleanup() {
  echo "Stopping processes..."
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
    fi
  done
}

trap cleanup EXIT INT TERM

PIDS=()

cd "${ROOT_DIR}"

start_process "MCP server" python run_mcp.py
start_process "Backend API" python run_api.py
start_process "Frontend" bash -lc "cd \"${ROOT_DIR}/src/frontend\" && npm run dev"

wait
