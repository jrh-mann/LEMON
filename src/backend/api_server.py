"""FastAPI + WebSocket API server for the LEMON web app."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.app import create_app
from .api.common import repo_root
from .api.conversations import ConversationStore
from .api.frontend import register_frontend_routes
from .api.routes import register_routes
from .api.ws_handler import register_ws_endpoint
from .api.ws_registry import ConnectionRegistry
from .storage.auth import AuthStore
from .storage.workflows import WorkflowStore
from .utils.paths import lemon_data_dir

_repo_root = repo_root()
_data_dir = lemon_data_dir(_repo_root)

# Shared instances — created once at import time
ws_registry = ConnectionRegistry()  # Event loop set lazily in lifespan
conversation_store = ConversationStore(_repo_root)
auth_store = AuthStore(_data_dir / "auth.sqlite")
workflow_store = WorkflowStore(_data_dir / "workflows.sqlite")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan — sets the event loop on the registry."""
    ws_registry.set_loop(asyncio.get_running_loop())
    yield


# Build the FastAPI app with lifespan for lazy event loop setup
app = create_app(lifespan=lifespan)

# Store auth_store on app.state so Depends() can read it via request.app.state
app.state.auth_store = auth_store

# Register REST routes (includes logging middleware)
register_routes(
    app,
    conversation_store=conversation_store,
    repo_root=_repo_root,
    auth_store=auth_store,
    workflow_store=workflow_store,
)

# Register WebSocket endpoint at /ws
register_ws_endpoint(
    app,
    ws_registry=ws_registry,
    conversation_store=conversation_store,
    repo_root=_repo_root,
    auth_store=auth_store,
    workflow_store=workflow_store,
)

# Serve frontend static files (SPA catch-all)
register_frontend_routes(app, _repo_root / "src" / "frontend" / "dist")
