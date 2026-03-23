"""Dev tools routes: list and execute tools.

Provides REST endpoints for the DevTools panel to enumerate
available tools and execute them with provided arguments.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, FastAPI, Request
from starlette.responses import JSONResponse

from ..deps import require_auth
from ...storage.auth import AuthUser
from ...storage.workflows import WorkflowStore
from .helpers import api_error
from ...agents.orchestrator_factory import build_orchestrator
from ...agents.request_context import (
    configure_orchestrator_for_request,
    hydrate_uploaded_files,
)
from ...workflow_persistence import persist_workflow_snapshot

logger = logging.getLogger("backend.api")


def _extract_tool_payload(payload: Any) -> tuple[Dict[str, Any], Dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}, {}
    raw_args = payload.get("args")
    raw_context = payload.get("context")
    if isinstance(raw_args, dict) or isinstance(raw_context, dict):
        return (
            raw_args if isinstance(raw_args, dict) else {},
            raw_context if isinstance(raw_context, dict) else {},
        )
    return payload, {}


def _normalize_tool_args(args: Dict[str, Any]) -> Dict[str, Any]:
    nested_args = args.get("args")
    if isinstance(nested_args, dict) and set(args.keys()) <= {"args", "context"}:
        return nested_args
    return args


def _tool_input_schema(tool: Any) -> Dict[str, Any]:
    schema_override = getattr(tool, "_schema_override", None)
    if isinstance(schema_override, dict):
        return schema_override

    properties = {}
    required_params = []
    for param in tool.parameters:
        prop: Dict[str, Any] = {
            "type": param.type,
            "description": param.description,
        }
        if getattr(param, "enum", None):
            prop["enum"] = list(param.enum)
        if getattr(param, "items", None):
            prop["items"] = param.items
        properties[param.name] = prop
        if param.required:
            required_params.append(param.name)

    return {
        "type": "object",
        "properties": properties,
        "required": required_params,
    }


def _persist_context_workflow(
    *,
    workflow_store: WorkflowStore,
    user_id: str,
    workflow_id: str,
    workflow_data: Dict[str, Any],
) -> None:
    persist_workflow_snapshot(
        workflow_store,
        workflow_id=workflow_id,
        user_id=user_id,
        name="New Workflow",
        description="",
        nodes=workflow_data.get("nodes", []),
        edges=workflow_data.get("edges", []),
        variables=workflow_data.get("variables", []),
        outputs=workflow_data.get("outputs", []),
        output_type=workflow_data.get("output_type"),
        is_draft=True,
    )


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
        """List all available tools with their schemas.

        Returns array of tools, each with name, description, and inputSchema.
        Used by the DevTools panel to show available tools for execution.
        """
        from ...tools import build_tool_registry

        try:
            registry = build_tool_registry(repo_root)
            tools = []
            for tool in registry.all_tools():
                tools.append(
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "inputSchema": _tool_input_schema(tool),
                    }
                )
            return JSONResponse({"tools": tools})
        except Exception as e:
            logger.exception("Failed to list tools: %s", e)
            return JSONResponse(
                {"error": "Failed to list tools", "tools": []}, status_code=500
            )

    @router.post("/api/tools/{tool_name}/execute")
    async def execute_tool(
        tool_name: str,
        request: Request,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        """Execute a tool with the provided arguments.

        Request body should contain the tool arguments as JSON.
        The user_id and session_state are automatically injected from the
        authenticated session, so tools work the same as via the orchestrator.
        Returns the tool execution result.
        """
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError):
            return api_error("Invalid JSON in request body")

        args, context = _extract_tool_payload(payload)
        args = _normalize_tool_args(args)
        current_workflow_id = context.get("current_workflow_id")
        workflow_data = (
            context.get("workflow") if isinstance(context.get("workflow"), dict) else {}
        )
        workflow_analysis = (
            context.get("analysis")
            if isinstance(context.get("analysis"), dict)
            else None
        )
        open_tabs = (
            context.get("open_tabs")
            if isinstance(context.get("open_tabs"), list)
            else []
        )
        has_live_workflow = bool(workflow_data) or bool(workflow_analysis)

        if current_workflow_id and workflow_data:
            try:
                _persist_context_workflow(
                    workflow_store=workflow_store,
                    user_id=user.id,
                    workflow_id=current_workflow_id,
                    workflow_data=workflow_data,
                )
            except Exception:
                logger.warning(
                    "Failed to persist dev tools workflow context for %s",
                    current_workflow_id,
                    exc_info=True,
                )

        try:
            orchestrator = build_orchestrator(repo_root)
            uploaded_files = (
                hydrate_uploaded_files(
                    workflow_store=workflow_store,
                    user_id=user.id,
                    workflow_id=current_workflow_id,
                    repo_root=repo_root,
                )
                if current_workflow_id
                else []
            )
            configure_orchestrator_for_request(
                orchestrator,
                workflow_store=workflow_store,
                user_id=user.id,
                current_workflow_id=current_workflow_id,
                repo_root=repo_root,
                open_tabs=open_tabs,
                uploaded_files=uploaded_files,
                workflow_data=workflow_data,
                workflow_analysis=workflow_analysis,
                refresh_from_db=bool(current_workflow_id) and not has_live_workflow,
            )

            result = orchestrator.run_tool(tool_name, args)
            return JSONResponse(
                {
                    "success": result.success,
                    "result": result.data,
                    "error": result.error,
                }
            )
        except Exception as e:
            logger.exception("Failed to execute tool %s: %s", tool_name, e)
            return JSONResponse(
                {"success": False, "error": f"Tool execution failed: {e}"},
                status_code=500,
            )

    app.include_router(router)
