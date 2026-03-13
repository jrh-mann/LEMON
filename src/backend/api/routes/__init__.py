"""Routes package for the LEMON API server.

Replaces the monolithic routes.py with focused sub-modules.
Each module registers its own FastAPI routes via a register_*() function
that creates an APIRouter and includes it on the app.
The top-level register_routes() delegates to all sub-modules.

Public API:
    register_routes() — called by api_server.py to wire up all endpoints.
    _infer_outputs_from_nodes() — re-exported for test compatibility.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from typing import Optional

from ...tasks.conversations import ConversationStore
from ...storage.auth import AuthStore
from ...storage.conversation_log import ConversationLogger
from ...storage.workflows import WorkflowStore

# Re-export for test file that imports this helper directly
from .helpers import _infer_outputs_from_nodes

from .middleware import RequestLoggingMiddleware
from .info_route import register_info_route
from .auth_routes import register_auth_routes
from .chat_routes import register_chat_routes
from .workflow_routes import register_workflow_routes
from .search_routes import register_search_routes
from .dev_tools_routes import register_dev_tools_routes
from .validation_routes import register_validation_routes
from .execution_routes import register_execution_routes
from .compilation_routes import register_compilation_routes
from .stepped_execution_routes import register_stepped_execution_routes

__all__ = ["register_routes", "_infer_outputs_from_nodes"]


def register_routes(
    app: FastAPI,
    *,
    conversation_store: ConversationStore,
    repo_root: Path,
    auth_store: AuthStore,
    workflow_store: WorkflowStore,
    conversation_logger: Optional[ConversationLogger] = None,
) -> None:
    """Register all HTTP routes on the FastAPI app.

    Delegates to focused sub-modules, passing only the dependencies
    each module requires. Called once at startup from api_server.py.

    Args:
        app: FastAPI application instance.
        conversation_store: In-memory conversation manager.
        repo_root: Repository root path.
        auth_store: Auth store for user/session persistence.
        workflow_store: Workflow storage backend.
    """
    # Middleware (request logging) — must be registered first
    app.add_middleware(RequestLoggingMiddleware)

    # Public info endpoint (no auth required)
    register_info_route(app)

    # Authentication (register, login, logout, me)
    register_auth_routes(app, auth_store=auth_store)

    # Chat (send message, get conversation)
    register_chat_routes(
        app,
        conversation_store=conversation_store,
        repo_root=repo_root,
        conversation_logger=conversation_logger,
        workflow_store=workflow_store,
    )

    # Workflow CRUD (list, create, get, delete, patch, update)
    register_workflow_routes(app, workflow_store=workflow_store, repo_root=repo_root)

    # Search and domain listing
    register_search_routes(app, workflow_store=workflow_store)

    # Dev tools (list/execute tools)
    register_dev_tools_routes(
        app, repo_root=repo_root, workflow_store=workflow_store
    )

    # Validation (validate workflow structure)
    register_validation_routes(app)

    # Execution (run a workflow with inputs)
    register_execution_routes(app, workflow_store=workflow_store)

    # Compilation (compile workflow to Python)
    register_compilation_routes(app, workflow_store=workflow_store)

    # Stepped execution (visual step-through with SSE streaming)
    register_stepped_execution_routes(app, workflow_store=workflow_store)
