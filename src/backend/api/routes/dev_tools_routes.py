"""Dev tools routes: list and execute MCP tools.

Provides REST endpoints for the DevTools panel to enumerate
available tools and execute them with provided arguments.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, Request
from starlette.responses import JSONResponse

from ..deps import require_auth
from ...storage.auth import AuthUser
from ...storage.workflows import WorkflowStore

logger = logging.getLogger("backend.api")


def register_dev_tools_routes(
    app: FastAPI,
    *,
    repo_root: Path,
    workflow_store: WorkflowStore,
) -> None:
    """Register dev tools endpoints on the FastAPI app.

    Args:
        app: FastAPI application instance.
        repo_root: Repository root path for tool registry construction.
        workflow_store: Workflow storage backend (injected into tool session state).
    """
    router = APIRouter()

    @router.get("/api/tools")
    async def list_tools(
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        """List all available MCP tools with their schemas.

        Returns array of tools, each with name, description, and inputSchema.
        Used by the DevTools panel to show available tools for execution.
        """
        from ...mcp_bridge.client import list_mcp_tools

        try:
            tools = list_mcp_tools()
            return JSONResponse({"tools": tools})
        except Exception as e:
            logger.exception("Failed to list MCP tools: %s", e)
            return JSONResponse({"error": str(e), "tools": []}, status_code=500)

    @router.post("/api/tools/{tool_name}/execute")
    async def execute_tool(
        tool_name: str,
        request: Request,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        """Execute an MCP tool with the provided arguments.

        Request body should contain the tool arguments as JSON.
        The user_id and session_state are automatically injected from the
        authenticated session, so tools work the same as via the orchestrator.
        Returns the tool execution result.
        """
        from ...tools import build_tool_registry

        try:
            payload = await request.json()
        except Exception:
            payload = {}

        # Build session_state like the orchestrator does
        # This allows tools to work with the same context as via chat
        session_state = {
            "current_workflow": {},
            "workflow_analysis": {"variables": [], "outputs": []},
            "current_workflow_id": None,
            "open_tabs": [],
            "workflow_store": workflow_store,
            "user_id": user.id,
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
            return JSONResponse({"success": success, "result": result})
        except Exception as e:
            logger.exception("Failed to execute tool %s: %s", tool_name, e)
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    app.include_router(router)
