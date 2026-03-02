"""Dev tools routes: list and execute MCP tools.

Provides REST endpoints for the DevTools panel to enumerate
available tools and execute them with provided arguments.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, g

from ...storage.workflows import WorkflowStore

logger = logging.getLogger("backend.api")


def register_dev_tools_routes(
    app: Flask,
    *,
    repo_root: Path,
    workflow_store: WorkflowStore,
) -> None:
    """Register dev tools endpoints on the Flask app.

    Args:
        app: Flask application instance.
        repo_root: Repository root path for tool registry construction.
        workflow_store: Workflow storage backend (injected into tool session state).
    """

    @app.get("/api/tools")
    def list_tools() -> Any:
        """List all available MCP tools with their schemas.

        Returns array of tools, each with name, description, and inputSchema.
        Used by the DevTools panel to show available tools for execution.
        """
        from ...mcp_bridge.client import list_mcp_tools

        try:
            tools = list_mcp_tools()
            return jsonify({"tools": tools})
        except Exception as e:
            logger.exception("Failed to list MCP tools: %s", e)
            return jsonify({"error": str(e), "tools": []}), 500

    @app.post("/api/tools/<tool_name>/execute")
    def execute_tool(tool_name: str) -> Any:
        """Execute an MCP tool with the provided arguments.

        Request body should contain the tool arguments as JSON.
        The user_id and session_state are automatically injected from the
        authenticated session, so tools work the same as via the orchestrator.
        Returns the tool execution result.
        """
        from ...tools import build_tool_registry

        payload = request.get_json(force=True, silent=True) or {}

        # Build session_state like the orchestrator does
        # This allows tools to work with the same context as via chat
        session_state = {
            "current_workflow": {},
            "workflow_analysis": {"variables": [], "outputs": []},
            "current_workflow_id": None,
            "open_tabs": [],
            "workflow_store": workflow_store,
            "user_id": g.auth_user.id if hasattr(g, "auth_user") else None,
        }

        try:
            # Build a fully populated registry with all discovered tools
            tools = build_tool_registry(repo_root)
            result = tools.execute(
                tool_name,
                payload,
                session_state=session_state,
            )
            # Normalize result
            if not isinstance(result, dict):
                result = {"result": result}
            success = result.get("success", "error" not in result)
            return jsonify({"success": success, "result": result})
        except Exception as e:
            logger.exception("Failed to execute tool %s: %s", tool_name, e)
            return jsonify({"success": False, "error": str(e)}), 500
