"""HTTP routes for the API server."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from flask import Flask, jsonify, request, make_response, g

from .common import utc_now
from .auth import (
    apply_login_rate_limit,
    clear_session_cookie,
    get_auth_config,
    get_session_from_request,
    hash_password,
    hash_session_token,
    issue_session,
    is_registration_allowed,
    note_login_failure,
    normalize_email,
    set_session_cookie,
    validate_email,
    validate_password,
    verify_password,
)
from .conversations import ConversationStore
from ..utils.uploads import save_uploaded_image
from .response_utils import extract_flowchart, extract_tool_calls, summarize_response
from ..storage.auth import AuthStore, AuthUser

logger = logging.getLogger("backend.api")


def register_routes(
    app: Flask,
    *,
    conversation_store: ConversationStore,
    repo_root: Path,
    auth_store: AuthStore,
) -> None:
    auth_config = get_auth_config()
    dummy_password_hash = hash_password("dummy-password", config=auth_config)
    allow_registration = is_registration_allowed()
    public_paths = {"/api/info", "/api/auth/login", "/api/auth/logout", "/api/auth/register"}

    @app.before_request
    def log_request() -> None:
        logger.info(
            "HTTP %s %s from %s",
            request.method,
            request.path,
            request.remote_addr,
        )

    @app.before_request
    def enforce_auth() -> Any:
        if request.method == "OPTIONS":
            return None
        if not request.path.startswith("/api/"):
            return None
        if request.path in public_paths:
            return None
        session_info = get_session_from_request(auth_store)
        if not session_info:
            return jsonify({"error": "Authentication required."}), 401
        session, user = session_info
        g.auth_session = session
        g.auth_user = user
        return None

    def serialize_user(user: AuthUser) -> Dict[str, str]:
        return {
            "id": user.id,
            "email": user.email,
            "name": user.name,
        }

    @app.get("/api/info")
    def api_info() -> Any:
        return jsonify(
            {
                "name": "LEMON Backend",
                "version": "0.1",
                "endpoints": {
                    "chat": "/api/chat",
                    "workflows": "/api/workflows",
                    "search": "/api/search",
                },
            }
        )

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
        response = make_response(jsonify({"user": {"id": user_id, "email": email, "name": name}}), 201)
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
        response = make_response(jsonify({"user": serialize_user(user)}))
        set_session_cookie(response, token, expires_at, config=auth_config)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/auth/logout")
    def logout_user() -> Any:
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
        response = make_response(jsonify({"user": serialize_user(user)}))
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/chat")
    def chat() -> Any:
        payload = request.get_json(force=True, silent=True) or {}
        message = payload.get("message", "")
        conversation_id = payload.get("conversation_id")
        image_data = payload.get("image")

        if not isinstance(message, str) or not message.strip():
            return jsonify({"error": "message is required"}), 400

        convo = conversation_store.get_or_create(conversation_id)
        if isinstance(image_data, str) and image_data.strip():
            try:
                save_uploaded_image(image_data, repo_root=repo_root)
            except Exception as exc:
                logger.exception("Failed to save uploaded image")
                return jsonify({"error": f"Invalid image data: {exc}"}), 400

        executed_tools: list[dict[str, Any]] = []

        def on_tool_event(
            event: str,
            tool: str,
            args: Dict[str, Any],
            result: Optional[Dict[str, Any]],
        ) -> None:
            if event == "tool_start":
                executed_tools.append({"tool": tool, "arguments": args})

        response_text = convo.orchestrator.respond(
            message,
            has_image=bool(image_data),
            allow_tools=True,
            on_tool_event=on_tool_event,
        )
        tool_calls = extract_tool_calls(response_text, include_result=False)
        if not tool_calls and executed_tools:
            tool_calls = executed_tools
        response_summary = summarize_response(response_text)
        flowchart = extract_flowchart(response_text)
        convo.updated_at = utc_now()
        return jsonify(
            {
                "conversation_id": convo.id,
                "response": response_summary,
                "tool_calls": tool_calls,
                "flowchart": flowchart,
            }
        )

    @app.get("/api/chat/<conversation_id>")
    def get_conversation(conversation_id: str) -> Any:
        convo = conversation_store.get(conversation_id)
        if not convo:
            return jsonify({"error": "conversation not found"}), 404
        messages = []
        for idx, msg in enumerate(convo.orchestrator.history):
            role = msg.get("role", "assistant")
            content = msg.get("content", "")
            messages.append(
                {
                    "id": f"{conversation_id}_{idx}",
                    "role": role,
                    "content": content,
                    "timestamp": utc_now(),
                    "tool_calls": extract_tool_calls(content),
                }
            )
        return jsonify(
            {
                "id": convo.id,
                "messages": messages,
                "working": {},
                "created_at": convo.created_at,
                "updated_at": convo.updated_at,
            }
        )

    @app.get("/api/workflows")
    def list_workflows() -> Any:
        return jsonify({"workflows": [], "count": 0})

    @app.post("/api/workflows")
    def create_workflow() -> Any:
        payload = request.get_json(force=True, silent=True) or {}
        workflow_id = f"wf_{uuid4().hex}"
        name = payload.get("name") or "Untitled Workflow"
        description = payload.get("description") or ""
        response = {
            "workflow_id": workflow_id,
            "name": name,
            "description": description,
            "domain": payload.get("domain"),
            "tags": payload.get("tags") or [],
            "nodes": [],
            "edges": [],
            "message": "Workflow created (placeholder).",
        }
        return jsonify(response)

    @app.get("/api/workflows/<workflow_id>")
    def get_workflow(workflow_id: str) -> Any:
        return jsonify({"error": "workflow storage not implemented"}), 404

    @app.delete("/api/workflows/<workflow_id>")
    def delete_workflow(workflow_id: str) -> Any:
        return jsonify({})

    @app.get("/api/search")
    def search_workflows() -> Any:
        return jsonify({"workflows": []})

    @app.get("/api/domains")
    def list_domains() -> Any:
        return jsonify({"domains": []})

    @app.post("/api/execute/<workflow_id>")
    def execute_workflow(workflow_id: str) -> Any:
        return jsonify(
            {
                "success": False,
                "error": "Workflow execution not implemented.",
                "path": [],
                "context": {},
            }
        )

    @app.post("/api/validation/start")
    def start_validation() -> Any:
        return jsonify({"error": "Validation not implemented."}), 501

    @app.post("/api/validation/submit")
    def submit_validation() -> Any:
        return jsonify({"error": "Validation not implemented."}), 501

    @app.get("/api/validation/<session_id>")
    def validation_status(session_id: str) -> Any:
        return jsonify({"error": "Validation not implemented."}), 501
