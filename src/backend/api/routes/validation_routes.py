"""Validation routes: validate workflow structure and validation stubs.

Provides the /api/validate endpoint for pre-save structural checks
and stub endpoints for the future validation session system.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, request


def register_validation_routes(app: Flask) -> None:
    """Register validation endpoints on the Flask app.

    Args:
        app: Flask application instance.
    """

    @app.post("/api/validate")
    def validate_workflow_endpoint() -> Any:
        """Validate a workflow structure before saving/exporting."""
        from ...validation.workflow_validator import WorkflowValidator

        payload = request.get_json(force=True, silent=True) or {}
        nodes = payload.get("nodes", [])
        edges = payload.get("edges", [])
        variables = payload.get("variables", [])

        validator = WorkflowValidator()
        workflow_to_validate = {
            "nodes": nodes,
            "edges": edges,
            "variables": variables,
        }

        # Use strict=True to check for unreachable nodes and complete structure
        is_valid, errors = validator.validate(workflow_to_validate, strict=True)

        if is_valid:
            return jsonify({
                "success": True,
                "valid": True,
                "message": (
                    "Workflow is valid. All nodes are reachable "
                    "and connected correctly."
                ),
            })
        else:
            error_message = validator.format_errors(errors)
            return jsonify({
                "success": True,
                "valid": False,
                "errors": [
                    {
                        "code": e.code,
                        "message": e.message,
                        "node_id": e.node_id,
                    }
                    for e in errors
                ],
                "message": error_message,
            })

    @app.post("/api/validation/start")
    def start_validation() -> Any:
        return jsonify({"error": "Validation not implemented."}), 501

    @app.post("/api/validation/submit")
    def submit_validation() -> Any:
        return jsonify({"error": "Validation not implemented."}), 501

    @app.get("/api/validation/<session_id>")
    def validation_status(session_id: str) -> Any:
        return jsonify({"error": "Validation not implemented."}), 501
