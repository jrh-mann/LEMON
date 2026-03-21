"""FastAPI dependencies for auth enforcement.

Usage in route files:
    @router.get("/api/workflows")
    async def list_workflows(user: AuthUser = Depends(require_auth)):
        ...

Auth store is read from request.app.state.auth_store — set once at startup
in api_server.py. No module-level globals.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from ..storage.auth import AuthUser
from .auth import get_session_from_cookies


async def require_auth(request: Request) -> AuthUser:
    """FastAPI dependency — rejects with 401 if not authenticated."""
    auth_store = request.app.state.auth_store
    session_info = get_session_from_cookies(auth_store, dict(request.cookies))
    if not session_info:
        raise HTTPException(status_code=401, detail="Authentication required.")
    _session, user = session_info
    return user


async def optional_auth(request: Request) -> AuthUser | None:
    """FastAPI dependency — returns None instead of 401 for public routes."""
    auth_store = request.app.state.auth_store
    session_info = get_session_from_cookies(auth_store, dict(request.cookies))
    if not session_info:
        return None
    _session, user = session_info
    return user
