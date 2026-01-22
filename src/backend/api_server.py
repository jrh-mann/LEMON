"""Flask + Socket.IO API server for the LEMON web app."""

from __future__ import annotations

from .api.app import create_app
from .api.common import repo_root
from .api.conversations import ConversationStore
from .api.routes import register_routes
from .api.socket_handlers import register_socket_handlers
from .api.socketio_server import create_socketio
from .storage.auth import AuthStore

_repo_root = repo_root()

app = create_app()
socketio = create_socketio(app)
conversation_store = ConversationStore(_repo_root)
auth_store = AuthStore(_repo_root / ".lemon" / "auth.sqlite")

register_routes(app, conversation_store=conversation_store, repo_root=_repo_root, auth_store=auth_store)
register_socket_handlers(
    socketio,
    conversation_store=conversation_store,
    repo_root=_repo_root,
    auth_store=auth_store,
)
