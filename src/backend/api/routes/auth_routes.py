"""Authentication routes: register, login, logout, me.

Handles user registration, login with rate limiting, session
management, and current-user queries.
"""

from __future__ import annotations

import sqlite3
from typing import Dict
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Request
from starlette.responses import JSONResponse

from ..auth import (
    apply_login_rate_limit,
    clear_session_cookie,
    get_auth_config,
    hash_password,
    issue_session,
    is_registration_allowed,
    note_login_failure,
    normalize_email,
    set_session_cookie,
    validate_email,
    validate_password,
    verify_password,
)
from ..deps import require_auth
from ...storage.auth import AuthStore, AuthUser


def _serialize_user(user: AuthUser) -> Dict[str, str]:
    """Serialize an AuthUser to a JSON-safe dict."""
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
    }


def register_auth_routes(app: FastAPI, *, auth_store: AuthStore) -> None:
    """Register authentication endpoints on the FastAPI app.

    Args:
        app: FastAPI application instance.
        auth_store: Auth store for user/session persistence.
    """
    router = APIRouter()
    auth_config = get_auth_config()
    # Pre-computed dummy hash for constant-time comparison on unknown emails
    dummy_password_hash = hash_password("dummy-password", config=auth_config)
    allow_registration = is_registration_allowed()

    @router.post("/api/auth/register")
    async def register_user(request: Request) -> JSONResponse:
        if not allow_registration:
            return JSONResponse({"error": "Registration is disabled."}, status_code=403)

        try:
            payload = await request.json()
        except Exception:
            payload = {}

        email = normalize_email(str(payload.get("email", "")))
        name = str(payload.get("name", "")).strip()
        password = str(payload.get("password", ""))
        remember = bool(payload.get("remember"))

        errors = []
        email_error = validate_email(email)
        if email_error:
            errors.append(email_error)
        if not name:
            errors.append("Name is required.")
        errors.extend(list(validate_password(password, auth_config)))
        if errors:
            return JSONResponse({"error": errors[0], "errors": errors}, status_code=400)

        user_id = f"user_{uuid4().hex}"
        password_hash = hash_password(password, config=auth_config)
        try:
            auth_store.create_user(user_id, email, name, password_hash)
        except sqlite3.IntegrityError:
            return JSONResponse({"error": "Email is already registered."}, status_code=409)

        token, expires_at = issue_session(
            auth_store,
            user_id=user_id,
            remember=remember,
            config=auth_config,
        )
        response = JSONResponse(
            {"user": {"id": user_id, "email": email, "name": name}},
            status_code=201,
        )
        set_session_cookie(response, token, expires_at, config=auth_config)
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.post("/api/auth/login")
    async def login_user(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = {}

        email = normalize_email(str(payload.get("email", "")))
        password = str(payload.get("password", ""))
        remember = bool(payload.get("remember"))

        email_error = validate_email(email)
        if email_error:
            return JSONResponse({"error": email_error}, status_code=400)

        # Use client IP for rate-limiting identifier
        client_host = request.client.host if request.client else "unknown"
        identifier = f"{client_host}:{email}"
        rate_limit_response = apply_login_rate_limit(identifier)
        if rate_limit_response is not None:
            return rate_limit_response

        user = auth_store.get_user_by_email(email)
        if not user:
            verify_password(password, dummy_password_hash)
            note_login_failure(identifier)
            return JSONResponse({"error": "Invalid email or password."}, status_code=401)

        if not verify_password(password, user.password_hash):
            note_login_failure(identifier)
            return JSONResponse({"error": "Invalid email or password."}, status_code=401)

        auth_store.update_last_login(user.id)
        token, expires_at = issue_session(
            auth_store,
            user_id=user.id,
            remember=remember,
            config=auth_config,
        )
        response = JSONResponse({"user": _serialize_user(user)})
        set_session_cookie(response, token, expires_at, config=auth_config)
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.post("/api/auth/logout")
    async def logout_user(request: Request) -> JSONResponse:
        from ..auth import hash_session_token

        token = request.cookies.get("lemon_session")
        if token:
            token_hash = hash_session_token(token)
            auth_store.delete_session_by_token_hash(token_hash)
        response = JSONResponse({"success": True})
        clear_session_cookie(response, config=auth_config)
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.get("/api/auth/me")
    async def auth_me(user: AuthUser = Depends(require_auth)) -> JSONResponse:
        response = JSONResponse({"user": _serialize_user(user)})
        response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(router)
