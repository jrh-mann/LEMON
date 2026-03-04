"""MCP server for LEMON backend tools.

Uses auto-discovery and auto-registration: all Tool subclasses under
backend.tools are found at startup and wrapped as MCP tools — no
manual imports or per-tool boilerplate required.
"""

from __future__ import annotations

import hmac
import logging
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings

from ..storage.workflows import WorkflowStore
from ..utils.logging import setup_logging
from ..utils.paths import lemon_data_dir
from ..tools.discovery import discover_tool_classes, _instantiate_tool
from .auto_register import register_tool_on_server

logger = logging.getLogger("backend.mcp")


# ------------------------------------------------------------------ #
# Auth helpers
# ------------------------------------------------------------------ #

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


# ------------------------------------------------------------------ #
# Server factory
# ------------------------------------------------------------------ #

def build_mcp_server(host: str | None = None, port: int | None = None) -> FastMCP:
    """Build a FastMCP server with all tools auto-registered from discovery."""
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

    # Shared WorkflowStore for MCP mode — MCP receives session_state by
    # value (over HTTP), so it needs its own store instance.
    _data_dir = lemon_data_dir(_repo_root())
    _workflow_store = WorkflowStore(_data_dir / "workflows.sqlite")

    # Auto-discover and register every Tool subclass
    tool_classes = discover_tool_classes()
    for tool_cls in tool_classes:
        tool = _instantiate_tool(tool_cls, _repo_root())
        register_tool_on_server(server, tool, _workflow_store, _repo_root())

    logger.info("Registered %d MCP tools via auto-discovery", len(tool_classes))
    return server


# ------------------------------------------------------------------ #
# Transport resolution & entrypoint
# ------------------------------------------------------------------ #

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
