"""Search and domain listing routes.

Handles workflow search with filters (GET /api/search) and
domain enumeration (GET /api/domains).
"""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, request, g

from .helpers import serialize_workflow_summary
from ...storage.workflows import WorkflowStore


def register_search_routes(
    app: Flask,
    *,
    workflow_store: WorkflowStore,
) -> None:
    """Register search endpoints on the Flask app.

    Args:
        app: Flask application instance.
        workflow_store: Workflow storage backend.
    """

    @app.get("/api/search")
    def search_workflows() -> Any:
        """Search workflows with filters.

        All workflows in the database are considered "saved" workflows.
        """
        user_id = g.auth_user.id
        query = request.args.get("q")
        domain = request.args.get("domain")
        validated = request.args.get("validated")
        limit = min(int(request.args.get("limit", 100)), 500)
        offset = max(int(request.args.get("offset", 0)), 0)

        # Convert validated string to bool if provided
        validated_bool = None
        if validated is not None:
            validated_bool = validated.lower() in ("true", "1", "yes")

        workflows, total_count = workflow_store.search_workflows(
            user_id,
            query=query,
            domain=domain,
            validated=validated_bool,
            limit=limit,
            offset=offset,
        )

        summaries = [serialize_workflow_summary(wf) for wf in workflows]
        return jsonify({"workflows": summaries, "count": total_count})

    @app.get("/api/domains")
    def list_domains() -> Any:
        """Get list of unique domains used in user's workflows."""
        user_id = g.auth_user.id
        domains = workflow_store.get_domains(user_id)
        return jsonify({"domains": domains})
