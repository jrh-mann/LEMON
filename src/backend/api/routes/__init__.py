"""Routes package for the LEMON API server.

Replaces the monolithic routes.py with focused sub-modules.
Each module registers its own Flask routes via a register_*() function.
The top-level register_routes() delegates to all sub-modules.

Public API:
    register_routes() — called by api_server.py to wire up all endpoints.
    _infer_outputs_from_nodes() — re-exported for test compatibility.
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask

from ..conversations import ConversationStore
from ...storage.auth import AuthStore
from ...storage.workflows import WorkflowStore

# Re-export for test file that imports this helper directly
from .helpers import _infer_outputs_from_nodes

from .middleware import register_middleware
from .info_route import register_info_route
from .auth_routes import register_auth_routes
from .chat_routes import register_chat_routes
from .workflow_routes import register_workflow_routes
from .search_routes import register_search_routes
from .peer_review_routes import register_peer_review_routes
from .dev_tools_routes import register_dev_tools_routes
from .validation_routes import register_validation_routes
from .execution_routes import register_execution_routes
from .compilation_routes import register_compilation_routes

__all__ = ["register_routes", "_infer_outputs_from_nodes"]


def register_routes(
    app: Flask,
    *,
    conversation_store: ConversationStore,
    repo_root: Path,
    auth_store: AuthStore,
    workflow_store: WorkflowStore,
) -> None:
    """Register all HTTP routes on the Flask app.

    Delegates to focused sub-modules, passing only the dependencies
    each module requires. Called once at startup from api_server.py.

    Args:
        app: Flask application instance.
        conversation_store: In-memory conversation manager.
        repo_root: Repository root path.
        auth_store: Auth store for user/session persistence.
        workflow_store: Workflow storage backend.
    """
    # Middleware (logging + auth enforcement) — must be registered first
    register_middleware(app, auth_store=auth_store)

    # Public info endpoint (no auth required)
    register_info_route(app)

    # Authentication (register, login, logout, me)
    register_auth_routes(app, auth_store=auth_store)

    # Chat (send message, get conversation)
    register_chat_routes(
        app,
        conversation_store=conversation_store,
        repo_root=repo_root,
    )

    # Workflow CRUD (list, create, get, delete, patch, update)
    register_workflow_routes(app, workflow_store=workflow_store)

    # Search and domain listing
    register_search_routes(app, workflow_store=workflow_store)

    # Peer review (public workflows, voting)
    register_peer_review_routes(app, workflow_store=workflow_store)

    # Dev tools (list/execute MCP tools)
    register_dev_tools_routes(
        app, repo_root=repo_root, workflow_store=workflow_store
    )

    # Validation (validate workflow structure)
    register_validation_routes(app)

    # Execution (run a workflow with inputs)
    register_execution_routes(app, workflow_store=workflow_store)

    # Compilation (compile workflow to Python)
    register_compilation_routes(app, workflow_store=workflow_store)
