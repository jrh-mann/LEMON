#!/bin/bash
set -euo pipefail

# Resolve app path; Oryx may extract to a temp dir and set APP_PATH.
APP_DIR="${APP_PATH:-/home/site/wwwroot}"

cd "$APP_DIR"
export PYTHONPATH="${PYTHONPATH:-$APP_DIR:$APP_DIR/src}"

exec gunicorn --bind="0.0.0.0:${PORT:-8000}" --timeout 600 frontend.app:app
