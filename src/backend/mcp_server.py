"""MCP server for LEMON backend tools."""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from .logging_utils import setup_logging
from .tools import AnalyzeWorkflowTool

logger = logging.getLogger("backend.mcp")


def _repo_root() -> Path:
    return Path(__file__).parent.parent.parent


def _decode_data_url(data_url: str) -> tuple[bytes, str]:
    if not data_url.startswith("data:"):
        raise ValueError("image_data_url must be a data URL.")
    header, _, b64 = data_url.partition(",")
    if not b64:
        raise ValueError("Invalid data URL payload.")
    media_type = header.split(";")[0].replace("data:", "")
    ext = "png"
    if media_type == "image/jpeg":
        ext = "jpg"
    elif media_type == "image/webp":
        ext = "webp"
    elif media_type == "image/gif":
        ext = "gif"
    elif media_type == "image/bmp":
        ext = "bmp"
    return base64.b64decode(b64), ext


def _save_uploaded_image(data_url: str) -> str:
    raw, ext = _decode_data_url(data_url)
    uploads_dir = _repo_root() / ".lemon" / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    filename = f"mcp_{os.urandom(8).hex()}.{ext}"
    path = uploads_dir / filename
    path.write_bytes(raw)
    return str(path.relative_to(_repo_root()))


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

    return server


def _resolve_transport() -> str:
    raw = os.environ.get("MCP_TRANSPORT", "stdio").strip().lower()
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
