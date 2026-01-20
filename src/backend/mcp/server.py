"""MCP server for LEMON backend tools."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from ..utils.logging import setup_logging
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
)
from ..utils.uploads import save_uploaded_image

logger = logging.getLogger("backend.mcp")


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
    server = FastMCP(
        name="LEMON MCP",
        instructions="Analyze workflow images and return structured workflow data.",
        host=host or "127.0.0.1",
        port=port or 8000,
        json_response=True,
        stateless_http=True,
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
