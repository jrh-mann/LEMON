"""Flask + Socket.IO API server for the LEMON web app."""

from __future__ import annotations

from .api.app import create_app
from .api.common import repo_root
from .api.conversations import ConversationStore
from .api.frontend import register_frontend_routes
from .api.routes import register_routes
from .api.socket_handlers import register_socket_handlers
from .api.socketio_server import create_socketio
from .storage.auth import AuthStore
from .utils.paths import lemon_data_dir

_repo_root = repo_root()
_data_dir = lemon_data_dir(_repo_root)

app = create_app()
socketio = create_socketio(app)
conversation_store = ConversationStore(_repo_root)
auth_store = AuthStore(_data_dir / "auth.sqlite")

register_routes(app, conversation_store=conversation_store, repo_root=_repo_root, auth_store=auth_store)
register_socket_handlers(
    socketio,
    conversation_store=conversation_store,
    repo_root=_repo_root,
    auth_store=auth_store,
)
register_frontend_routes(app, _repo_root / "src" / "frontend" / "dist")
