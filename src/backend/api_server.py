"""FastAPI API server for the LEMON web app.

All streaming goes through SSE (Server-Sent Events) via HTTP.
Chat messages stream via POST /api/chat/send → EventSink → StreamingResponse.
Execution events stream via POST /api/workflows/{id}/execute → EventSink → StreamingResponse.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.app import create_app
from .api.common import repo_root
from .api.conversations import ConversationStore
from .api.frontend import register_frontend_routes
from .api.routes import register_routes
from .storage.auth import AuthStore
from .storage.conversation_log import ConversationLogger
from .storage.workflows import WorkflowStore
from .utils.paths import lemon_data_dir

_repo_root = repo_root()
_data_dir = lemon_data_dir(_repo_root)

# Shared instances -- created once at import time
conversation_logger = ConversationLogger(_data_dir / "conversation_log.sqlite")
# Pass conversation_logger so ConversationStore can reload history after backend restart
conversation_store = ConversationStore(_repo_root, conversation_logger=conversation_logger)
auth_store = AuthStore(_data_dir / "auth.sqlite")
workflow_store = WorkflowStore(_data_dir / "workflows.sqlite")

_startup_logger = logging.getLogger("backend.api")
_startup_logger.info(
    "ConversationLogger initialized: %s", _data_dir / "conversation_log.sqlite",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan -- cleans up stale state on startup."""
    # Clear building=True flags left by daemon threads that died on last shutdown
    workflow_store.clear_stale_building_flags()
    yield


# Build the FastAPI app with lifespan
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

# Serve frontend static files (SPA catch-all) -- must come after API routes
register_frontend_routes(fastapi_app, _repo_root / "src" / "frontend" / "dist")

# The ASGI app — FastAPI handles everything (no socket wrapper)
app = fastapi_app
