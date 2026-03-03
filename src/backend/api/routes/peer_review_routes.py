"""Peer review routes: list/get/vote on public workflows.

Handles the community peer-review system where users can browse
published workflows, view full details, and cast votes.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, request, g

from .helpers import _calculate_confidence, serialize_workflow_summary
from ...storage.workflows import WorkflowStore, PUBLISH_VOTE_THRESHOLD


def register_peer_review_routes(
    app: Flask,
    *,
    workflow_store: WorkflowStore,
) -> None:
    """Register peer review endpoints on the Flask app.

    Args:
        app: Flask application instance.
        workflow_store: Workflow storage backend.
    """

    @app.get("/api/workflows/public")
    def list_public_workflows() -> Any:
        """List published workflows for peer review.

        Query params:
            review_status: "unreviewed" or "reviewed" (default: all)
            limit: max results (default 100)
            offset: pagination offset
        """
        review_status = request.args.get("review_status")
        limit = min(int(request.args.get("limit", 100)), 500)
        offset = max(int(request.args.get("offset", 0)), 0)

        # Validate review_status if provided
        if review_status and review_status not in ("unreviewed", "reviewed"):
            return jsonify({
                "error": "review_status must be 'unreviewed' or 'reviewed'"
            }), 400

        workflows, total_count = workflow_store.list_published_workflows(
            review_status=review_status,
            limit=limit,
            offset=offset,
        )

        # Get current user for vote lookup
        user_id = g.auth_user.id

        # Convert to summary format with peer review fields
        summaries = []
        for wf in workflows:
            # Start with the standard summary fields
            summary = serialize_workflow_summary(wf)
            # Append peer-review-specific fields
            summary.update({
                "is_published": wf.is_published,
                "review_status": wf.review_status,
                "net_votes": wf.net_votes,
                "published_at": wf.published_at,
                "publisher_id": wf.user_id,
                "user_vote": workflow_store.get_user_vote(wf.id, user_id),
            })
            summaries.append(summary)

        return jsonify({
            "workflows": summaries,
            "count": total_count,
            "publish_threshold": PUBLISH_VOTE_THRESHOLD,
        })

    @app.get("/api/workflows/public/<workflow_id>")
    def get_public_workflow(workflow_id: str) -> Any:
        """Get a specific published workflow by ID.

        Returns full workflow data for viewing/cloning.
        Also includes the current user's vote (if any).
        """
        user_id = g.auth_user.id
        workflow = workflow_store.get_published_workflow(workflow_id)

        if not workflow:
            return jsonify({"error": "Published workflow not found"}), 404

        # Get user's vote on this workflow
        user_vote = workflow_store.get_user_vote(workflow_id, user_id)

        response = {
            "id": workflow.id,
            "metadata": {
                "name": workflow.name,
                "description": workflow.description,
                "domain": workflow.domain,
                "tags": workflow.tags,
                "publisher_id": workflow.user_id,
                "created_at": workflow.created_at,
                "updated_at": workflow.updated_at,
                "validation_score": workflow.validation_score,
                "validation_count": workflow.validation_count,
                "confidence": _calculate_confidence(
                    workflow.validation_score, workflow.validation_count
                ),
                "is_validated": workflow.is_validated,
            },
            "nodes": workflow.nodes,
            "edges": workflow.edges,
            "variables": workflow.inputs,  # Storage field is 'inputs', API exposes as 'variables'
            "outputs": workflow.outputs,
            "tree": workflow.tree,
            # Peer review fields
            "review_status": workflow.review_status,
            "net_votes": workflow.net_votes,
            "published_at": workflow.published_at,
            "user_vote": user_vote,
        }
        return jsonify(response)

    @app.post("/api/workflows/public/<workflow_id>/vote")
    def vote_on_workflow(workflow_id: str) -> Any:
        """Cast or update a vote on a published workflow.

        Request body: { "vote": 1 } for upvote or { "vote": -1 } for downvote
        Use { "vote": 0 } or DELETE to remove vote.

        When a workflow reaches 3+ net votes, it's automatically promoted
        from "unreviewed" to "reviewed" status.
        """
        user_id = g.auth_user.id
        payload = request.get_json(force=True, silent=True) or {}
        vote = payload.get("vote")

        if vote is None:
            return jsonify({
                "error": "vote is required (+1, -1, or 0 to remove)"
            }), 400

        vote = int(vote)

        # Handle vote removal
        if vote == 0:
            result = workflow_store.remove_vote(workflow_id, user_id)
        elif vote in (-1, 1):
            result = workflow_store.cast_vote(workflow_id, user_id, vote)
        else:
            return jsonify({"error": "vote must be +1, -1, or 0"}), 400

        if not result.get("success"):
            return jsonify({
                "error": result.get("error", "Failed to cast vote")
            }), 400

        return jsonify(result)
