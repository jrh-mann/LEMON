"""Compilation routes: compile workflow to Python code.

Handles the /api/workflows/compile endpoint which converts a
workflow definition (nodes, edges, variables) into standalone
Python source code.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, request, g

from ...storage.workflows import WorkflowStore


def register_compilation_routes(
    app: Flask,
    *,
    workflow_store: WorkflowStore,
) -> None:
    """Register compilation endpoints on the Flask app.

    Args:
        app: Flask application instance.
        workflow_store: Workflow storage backend for subflow resolution.
    """

    @app.post("/api/workflows/compile")
    def compile_workflow_to_python_endpoint() -> Any:
        """Compile a workflow to Python code.

        Request body:
        {
            "nodes": [...],
            "edges": [...],
            "variables": [...],
            "outputs": [...],  # optional
            "name": "Workflow Name",  # optional
            "include_imports": true,  # optional, default true
            "include_docstring": true,  # optional, default true
            "include_main": false  # optional, default false
        }

        Returns:
        {
            "success": true,
            "code": "def workflow_name(...): ...",
            "warnings": []
        }
        """
        from ...execution.python_compiler import compile_workflow_to_python

        payload = request.get_json(force=True, silent=True) or {}
        nodes = payload.get("nodes", [])
        edges = payload.get("edges", [])
        variables = payload.get("variables", [])
        outputs = payload.get("outputs")
        workflow_name = payload.get("name", "workflow")

        # Optional generation flags
        include_imports = payload.get("include_imports", True)
        include_docstring = payload.get("include_docstring", True)
        include_main = payload.get("include_main", False)

        # Validate required fields
        if not nodes:
            return jsonify({
                "success": False,
                "error": "No nodes provided",
                "code": None,
                "warnings": [],
            }), 400

        # Closure to securely fetch subflows within user's permission domain
        def _fetch_subworkflow(sub_id: str):
            return workflow_store.get_workflow(
                sub_id,
                getattr(g, "auth_user", None).id
                if hasattr(g, "auth_user")
                else None,
            )

        # Compile workflow to Python
        result = compile_workflow_to_python(
            nodes=nodes,
            edges=edges,
            variables=variables,
            outputs=outputs,
            workflow_name=workflow_name,
            include_imports=include_imports,
            include_docstring=include_docstring,
            include_main=include_main,
            fetch_subworkflow=_fetch_subworkflow,
        )

        if result.success:
            return jsonify({
                "success": True,
                "code": result.code,
                "warnings": result.warnings,
            })
        else:
            return jsonify({
                "success": False,
                "error": result.error,
                "code": None,
                "warnings": result.warnings,
            }), 400
