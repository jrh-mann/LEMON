"""FastAPI + Socket.IO API server for the LEMON web app."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import socketio as socketio_pkg
from fastapi import FastAPI

from .api.app import create_app
from .api.common import repo_root
from .api.conversations import ConversationStore
from .api.frontend import register_frontend_routes
from .api.routes import register_routes
from .api.ws_handler import sio, create_registry, register_sio_events
from .storage.auth import AuthStore
from .storage.conversation_log import ConversationLogger
from .storage.workflows import WorkflowStore
from .utils.paths import lemon_data_dir

_repo_root = repo_root()
_data_dir = lemon_data_dir(_repo_root)

# Shared instances -- created once at import time
ws_registry = create_registry()  # Wraps the module-level sio server
conversation_store = ConversationStore(_repo_root)
auth_store = AuthStore(_data_dir / "auth.sqlite")
workflow_store = WorkflowStore(_data_dir / "workflows.sqlite")
conversation_logger = ConversationLogger(_data_dir / "conversation_log.sqlite")

_startup_logger = logging.getLogger("backend.api")
_startup_logger.info(
    "ConversationLogger initialized: %s", _data_dir / "conversation_log.sqlite",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan -- sets the event loop on the registry and cleans up stale state."""
    ws_registry.set_loop(asyncio.get_running_loop())
    # Clear building=True flags left by daemon threads that died on last shutdown
    workflow_store.clear_stale_building_flags()
    yield


# Build the FastAPI app with lifespan for lazy event loop setup
fastapi_app = create_app(lifespan=lifespan)

# Store auth_store on app.state so Depends() can read it via request.app.state
fastapi_app.state.auth_store = auth_store

# Register REST routes (includes logging middleware)
register_routes(
    fastapi_app,
    conversation_store=conversation_store,
    repo_root=_repo_root,
    auth_store=auth_store,
    workflow_store=workflow_store,
    conversation_logger=conversation_logger,
)

# Register Socket.IO event handlers (connect, disconnect, chat, etc.)
register_sio_events(
    ws_registry=ws_registry,
    conversation_store=conversation_store,
    repo_root=_repo_root,
    auth_store=auth_store,
    workflow_store=workflow_store,
    conversation_logger=conversation_logger,
)

# Serve frontend static files (SPA catch-all) -- must come after API routes
register_frontend_routes(fastapi_app, _repo_root / "src" / "frontend" / "dist")

# Mount Socket.IO as the top-level ASGI app, wrapping FastAPI.
# Socket.IO intercepts /socket.io/ requests and passes everything else
# through to the FastAPI app.
app = socketio_pkg.ASGIApp(sio, other_asgi_app=fastapi_app)
