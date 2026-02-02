"""MCP server for LEMON backend tools."""

from __future__ import annotations

import hmac
import logging
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from pydantic import BaseModel, ConfigDict, Field

from ..storage.workflows import WorkflowStore
from ..utils.logging import setup_logging
from ..utils.paths import lemon_data_dir
from ..tools import (
    AnalyzeWorkflowTool,
    PublishLatestAnalysisTool,
    GetCurrentWorkflowTool,
    AddNodeTool,
    ModifyNodeTool,
    DeleteNodeTool,
    AddConnectionTool,
    DeleteConnectionTool,
    BatchEditWorkflowTool,
    AddWorkflowVariableTool,
    ListWorkflowVariablesTool,
    ModifyWorkflowVariableTool,
    RemoveWorkflowVariableTool,
    SetWorkflowOutputTool,
    ValidateWorkflowTool,
    ListWorkflowsInLibrary,
)
from ..utils.uploads import save_uploaded_image

logger = logging.getLogger("backend.mcp")


class StaticTokenVerifier(TokenVerifier):
    def __init__(self, token: str, client_id: str, scopes: list[str]):
        self._token = token
        self._client_id = client_id
        self._scopes = scopes

    async def verify_token(self, token: str) -> AccessToken | None:
        if not hmac.compare_digest(token, self._token):
            return None
        return AccessToken(token=token, client_id=self._client_id, scopes=self._scopes)


def _auth_settings() -> tuple[AuthSettings | None, TokenVerifier | None]:
    token = os.environ.get("LEMON_MCP_AUTH_TOKEN", "").strip()
    if not token:
        return None, None
    issuer_url = os.environ.get("LEMON_MCP_ISSUER_URL", "http://127.0.0.1:8000").strip()
    resource_url = os.environ.get("LEMON_MCP_RESOURCE_URL", issuer_url).strip()
    scopes_raw = os.environ.get("LEMON_MCP_REQUIRED_SCOPES", "").strip()
    scopes = [scope.strip() for scope in scopes_raw.split(",") if scope.strip()]
    client_id = os.environ.get("LEMON_MCP_CLIENT_ID", "lemon-backend").strip()
    auth_settings = AuthSettings(
        issuer_url=issuer_url,
        resource_server_url=resource_url,
        required_scopes=scopes or None,
    )
    return auth_settings, StaticTokenVerifier(token=token, client_id=client_id, scopes=scopes)


def _repo_root() -> Path:
    return Path(__file__).parent.parent.parent.parent


def _save_uploaded_image(data_url: str) -> str:
    return save_uploaded_image(
        data_url,
        repo_root=_repo_root(),
        filename_prefix=f"mcp_{os.urandom(8).hex()}_",
    )


class Analysis(BaseModel):
    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    tree: dict[str, Any] = {}
    doubts: list[str] = []

    model_config = ConfigDict(extra="allow")


class FlowNode(BaseModel):
    id: str
    type: str
    label: str
    x: float
    y: float

    model_config = ConfigDict(extra="allow")


class FlowEdge(BaseModel):
    from_node: str = Field(alias="from")
    to: str
    label: str = ""
    id: str | None = None

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class Flowchart(BaseModel):
    nodes: list[FlowNode] = []
    edges: list[FlowEdge] = []

    model_config = ConfigDict(extra="allow")


class AnalyzeWorkflowResult(BaseModel):
    session_id: str
    analysis: Analysis
    flowchart: Flowchart

    model_config = ConfigDict(extra="allow")


def build_mcp_server(host: str | None = None, port: int | None = None) -> FastMCP:
    setup_logging()
    auth_settings, token_verifier = _auth_settings()
    if auth_settings and token_verifier:
        logger.info("MCP auth enabled")
    server = FastMCP(
        name="LEMON MCP",
        instructions="Analyze workflow images and return structured workflow data.",
        host=host or "127.0.0.1",
        port=port or 8000,
        json_response=True,
        stateless_http=True,
        auth=auth_settings,
        token_verifier=token_verifier,
    )
    tool = AnalyzeWorkflowTool(_repo_root())
    publish_tool = PublishLatestAnalysisTool(_repo_root())

    # Workflow manipulation tools
    get_workflow_tool = GetCurrentWorkflowTool()
    add_node_tool = AddNodeTool()
    modify_node_tool = ModifyNodeTool()
    delete_node_tool = DeleteNodeTool()
    add_conn_tool = AddConnectionTool()
    delete_conn_tool = DeleteConnectionTool()
    batch_edit_tool = BatchEditWorkflowTool()

    # Workflow variable management tools
    add_variable_tool = AddWorkflowVariableTool()
    list_variables_tool = ListWorkflowVariablesTool()
    modify_variable_tool = ModifyWorkflowVariableTool()
    remove_variable_tool = RemoveWorkflowVariableTool()
    set_output_tool = SetWorkflowOutputTool()
    validate_tool = ValidateWorkflowTool()

    @server.tool(
        name="analyze_workflow",
        description=(
            "Analyze the most recently uploaded workflow image and return inputs, outputs, "
            "doubts, and a flowchart representation."
        ),
    )
    def analyze_workflow(
        image_data_url: str | None = None,
        session_id: str | None = None,
        feedback: str | None = None,
    ) -> AnalyzeWorkflowResult:
        logger.info("MCP analyze_workflow start session_id=%s has_image=%s", session_id, bool(image_data_url))
        if session_id:
            if not feedback:
                raise ValueError("feedback is required when session_id is provided.")
        if image_data_url:
            _save_uploaded_image(image_data_url)

        args: dict[str, Any] = {}
        if session_id:
            args["session_id"] = session_id
        if feedback:
            args["feedback"] = feedback

        result = tool.execute(args)
        logger.info("MCP analyze_workflow complete session_id=%s", result.get("session_id"))
        return AnalyzeWorkflowResult.model_validate(result)

    @server.tool(
        name="publish_latest_analysis",
        description=(
            "Load the most recent workflow analysis and return it for rendering on the canvas."
        ),
    )
    def publish_latest_analysis() -> AnalyzeWorkflowResult:
        logger.info("MCP publish_latest_analysis start")
        result = publish_tool.execute({})
        logger.info("MCP publish_latest_analysis complete session_id=%s", result.get("session_id"))
        return AnalyzeWorkflowResult.model_validate(result)

    @server.tool(name="get_current_workflow")
    def get_current_workflow(session_state: dict[str, Any] | None = None) -> dict[str, Any]:
        return get_workflow_tool.execute({}, session_state=session_state or {})

    @server.tool(name="add_node")
    def add_node(
        type: str,
        label: str,
        x: float | None = None,
        y: float | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        args = {"type": type, "label": label}
        if x is not None:
            args["x"] = x
        if y is not None:
            args["y"] = y
        return add_node_tool.execute(args, session_state=session_state or {})

    @server.tool(name="modify_node")
    def modify_node(
        node_id: str,
        label: str | None = None,
        type: str | None = None,
        x: float | None = None,
        y: float | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        args = {"node_id": node_id}
        if label is not None:
            args["label"] = label
        if type is not None:
            args["type"] = type
        if x is not None:
            args["x"] = x
        if y is not None:
            args["y"] = y
        return modify_node_tool.execute(args, session_state=session_state or {})

    @server.tool(name="delete_node")
    def delete_node(
        node_id: str,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return delete_node_tool.execute({"node_id": node_id}, session_state=session_state or {})

    @server.tool(name="add_connection")
    def add_connection(
        from_node_id: str,
        to_node_id: str,
        label: str | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        args = {"from_node_id": from_node_id, "to_node_id": to_node_id}
        if label is not None:
            args["label"] = label
        return add_conn_tool.execute(args, session_state=session_state or {})

    @server.tool(name="delete_connection")
    def delete_connection(
        from_node_id: str,
        to_node_id: str,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return delete_conn_tool.execute(
            {"from_node_id": from_node_id, "to_node_id": to_node_id},
            session_state=session_state or {},
        )

    @server.tool(name="batch_edit_workflow")
    def batch_edit_workflow(
        operations: list[dict[str, Any]],
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return batch_edit_tool.execute({"operations": operations}, session_state=session_state or {})

    @server.tool(name="add_workflow_variable")
    def add_workflow_variable(
        name: str,
        type: str,
        description: str | None = None,
        enum_values: list[str] | None = None,
        range_min: float | None = None,
        range_max: float | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {"name": name, "type": type}
        if description:
            args["description"] = description
        if enum_values:
            args["enum_values"] = enum_values
        if range_min is not None:
            args["range_min"] = range_min
        if range_max is not None:
            args["range_max"] = range_max
        return add_variable_tool.execute(args, session_state=session_state or {})

    @server.tool(name="list_workflow_variables")
    def list_workflow_variables(
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return list_variables_tool.execute({}, session_state=session_state or {})

    @server.tool(name="remove_workflow_variable")
    def remove_workflow_variable(
        name: str,
        force: bool = False,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {"name": name}
        if force:
            args["force"] = force
        return remove_variable_tool.execute(args, session_state=session_state or {})

    @server.tool(name="modify_workflow_variable")
    def modify_workflow_variable(
        name: str,
        new_type: str | None = None,
        new_name: str | None = None,
        description: str | None = None,
        enum_values: list[str] | None = None,
        range_min: float | None = None,
        range_max: float | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {"name": name}
        if new_type is not None:
            args["new_type"] = new_type
        if new_name is not None:
            args["new_name"] = new_name
        if description is not None:
            args["description"] = description
        if enum_values is not None:
            args["enum_values"] = enum_values
        if range_min is not None:
            args["range_min"] = range_min
        if range_max is not None:
            args["range_max"] = range_max
        return modify_variable_tool.execute(args, session_state=session_state or {})

    @server.tool(name="set_workflow_output")
    def set_workflow_output(
        name: str,
        type: str,
        description: str | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {"name": name, "type": type}
        if description is not None:
            args["description"] = description
        return set_output_tool.execute(args, session_state=session_state or {})

    @server.tool(name="validate_workflow")
    def validate_workflow(
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return validate_tool.execute({}, session_state=session_state or {})

    # Workflow library tools — needs its own WorkflowStore since MCP can't
    # receive the live object from the orchestrator's session_state.
    _data_dir = lemon_data_dir(_repo_root())
    _workflow_store = WorkflowStore(_data_dir / "workflows.sqlite")
    list_library_tool = ListWorkflowsInLibrary()

    @server.tool(name="list_workflows_in_library")
    def list_workflows_in_library(
        search_query: str | None = None,
        domain: str | None = None,
        limit: int = 50,
        session_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {}
        if search_query is not None:
            args["search_query"] = search_query
        if domain is not None:
            args["domain"] = domain
        args["limit"] = limit
        # Inject workflow_store so the tool can query the DB in MCP mode
        state = dict(session_state or {})
        state.setdefault("workflow_store", _workflow_store)
        return list_library_tool.execute(args, session_state=state)

    return server


def _resolve_transport() -> str:
    raw = os.environ.get("MCP_TRANSPORT", "streamable-http").strip().lower()
    transport_map = {
        "stdio": "stdio",
        "sse": "sse",
        "streamable-http": "streamable-http",
        "http": "streamable-http",
        "streamable": "streamable-http",
    }
    transport = transport_map.get(raw)
    if not transport:
        raise ValueError(
            f"Unknown MCP_TRANSPORT '{raw}'. Use stdio, sse, or streamable-http."
        )
    return transport


def main() -> None:
    transport = _resolve_transport()
    host = os.environ.get("MCP_HOST") or "127.0.0.1"
    port = int(os.environ.get("MCP_PORT", "8000"))
    server = build_mcp_server(host=host, port=port)
    logger.info("Starting MCP server transport=%s host=%s port=%s", transport, host, port)
    server.run(transport=transport)


if __name__ == "__main__":
    main()
