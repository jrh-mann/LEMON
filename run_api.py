#!/usr/bin/env python3
"""Run the LEMON v2 API server."""

import sys
from pathlib import Path

# Critical: Add src to path BEFORE any imports
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

# Now we can import - but we need to avoid the main lemon/__init__.py
# So we import the app module directly
import importlib.util

app_path = src_path / "lemon" / "api" / "app.py"
spec = importlib.util.spec_from_file_location("lemon_api_app", app_path)
app_module = importlib.util.module_from_spec(spec)

# Temporarily remove lemon from modules to avoid init conflict
if "lemon" in sys.modules:
    del sys.modules["lemon"]

spec.loader.exec_module(app_module)

if __name__ == "__main__":
    # Use Socket.IO server so websocket events work in the web UI.
    app_module.socketio.run(
        app_module.app,
        debug=True,
        port=5001,
        allow_unsafe_werkzeug=True,
    )
