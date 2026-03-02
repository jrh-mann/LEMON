"""Authentication routes: register, login, logout, me.

Handles user registration, login with rate limiting, session
management, and current-user queries.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict
from uuid import uuid4

from flask import Flask, jsonify, request, make_response, g

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
from ...storage.auth import AuthStore, AuthUser


def _serialize_user(user: AuthUser) -> Dict[str, str]:
    """Serialize an AuthUser to a JSON-safe dict."""
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
    }


def register_auth_routes(app: Flask, *, auth_store: AuthStore) -> None:
    """Register authentication endpoints on the Flask app.

    Args:
        app: Flask application instance.
        auth_store: Auth store for user/session persistence.
    """
    auth_config = get_auth_config()
    # Pre-computed dummy hash for constant-time comparison on unknown emails
    dummy_password_hash = hash_password("dummy-password", config=auth_config)
    allow_registration = is_registration_allowed()

    @app.post("/api/auth/register")
    def register_user() -> Any:
        if not allow_registration:
            return jsonify({"error": "Registration is disabled."}), 403
        payload = request.get_json(force=True, silent=True) or {}
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
            return jsonify({"error": errors[0], "errors": errors}), 400

        user_id = f"user_{uuid4().hex}"
        password_hash = hash_password(password, config=auth_config)
        try:
            auth_store.create_user(user_id, email, name, password_hash)
        except sqlite3.IntegrityError:
            return jsonify({"error": "Email is already registered."}), 409

        token, expires_at = issue_session(
            auth_store,
            user_id=user_id,
            remember=remember,
            config=auth_config,
        )
        response = make_response(
            jsonify({"user": {"id": user_id, "email": email, "name": name}}),
            201,
        )
        set_session_cookie(response, token, expires_at, config=auth_config)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/auth/login")
    def login_user() -> Any:
        payload = request.get_json(force=True, silent=True) or {}
        email = normalize_email(str(payload.get("email", "")))
        password = str(payload.get("password", ""))
        remember = bool(payload.get("remember"))

        email_error = validate_email(email)
        if email_error:
            return jsonify({"error": email_error}), 400

        identifier = f"{request.remote_addr or 'unknown'}:{email}"
        rate_limit_response = apply_login_rate_limit(identifier)
        if rate_limit_response is not None:
            return rate_limit_response

        user = auth_store.get_user_by_email(email)
        if not user:
            verify_password(password, dummy_password_hash)
            note_login_failure(identifier)
            return jsonify({"error": "Invalid email or password."}), 401

        if not verify_password(password, user.password_hash):
            note_login_failure(identifier)
            return jsonify({"error": "Invalid email or password."}), 401

        auth_store.update_last_login(user.id)
        token, expires_at = issue_session(
            auth_store,
            user_id=user.id,
            remember=remember,
            config=auth_config,
        )
        response = make_response(jsonify({"user": _serialize_user(user)}))
        set_session_cookie(response, token, expires_at, config=auth_config)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/auth/logout")
    def logout_user() -> Any:
        from ..auth import hash_session_token

        token = request.cookies.get("lemon_session")
        if token:
            token_hash = hash_session_token(token)
            auth_store.delete_session_by_token_hash(token_hash)
        response = make_response(jsonify({"success": True}))
        clear_session_cookie(response, config=auth_config)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/auth/me")
    def auth_me() -> Any:
        user = getattr(g, "auth_user", None)
        if not user:
            return jsonify({"error": "Authentication required."}), 401
        response = make_response(jsonify({"user": _serialize_user(user)}))
        response.headers["Cache-Control"] = "no-store"
        return response
