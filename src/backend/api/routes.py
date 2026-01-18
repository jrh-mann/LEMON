"""HTTP routes for the API server."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from flask import Flask, jsonify, request

from .common import utc_now
from .conversations import ConversationStore
from ..utils.uploads import save_uploaded_image
from .response_utils import extract_flowchart, extract_tool_calls, summarize_response

logger = logging.getLogger("backend.api")


def register_routes(
    app: Flask,
    *,
    conversation_store: ConversationStore,
    repo_root: Path,
) -> None:
    @app.before_request
    def log_request() -> None:
        logger.info(
            "HTTP %s %s from %s",
            request.method,
            request.path,
            request.remote_addr,
        )

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

        response_text = convo.orchestrator.respond(
            message,
            has_image=bool(image_data),
            allow_tools=True,
        )
        tool_calls = extract_tool_calls(response_text, include_result=False)
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
