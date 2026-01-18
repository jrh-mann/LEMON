"""
Thin async MCP client wrapper for the C# UI automation server.
"""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .logging import get_logger


@dataclass
class McpProcessConfig:
    """
    Configuration for launching the C# MCP server.
    """

    dll_path: Path

    @classmethod
    def auto(cls) -> "McpProcessConfig":
        root = Path(__file__).resolve().parents[3]  # repo root
        dll = root / "src" / "csharp" / "UiAutomationServer" / "bin" / "Debug" / "net9.0-windows" / "UiAutomationExecutor.dll"
        if not dll.exists():
            raise FileNotFoundError(
                f"UI Automation DLL not found at {dll}. Build the C# project first (dotnet build)."
            )
        return cls(dll_path=dll)


class McpClient:
    """
    Manages MCP stdio connection and tool calls.
    """

    def __init__(self, config: Optional[McpProcessConfig] = None):
        self.config = config or McpProcessConfig.auto()
        self.logger = get_logger("mcp")
        self.tool_result_logger = get_logger("tool_results", file_name="tool_results.log")
        self._session: Optional[ClientSession] = None
        self._client_ctx = None
        self._read = None
        self._write = None
        self.tools: Dict[str, Any] = {}

    async def __aenter__(self) -> "McpClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.disconnect()

    async def connect(self) -> None:
        """
        Start the C# server (dotnet <dll>) and establish MCP session.
        """
        params = StdioServerParameters(command="dotnet", args=[str(self.config.dll_path)], env=None)
        self._client_ctx = stdio_client(params)
        self._read, self._write = await self._client_ctx.__aenter__()

        session_ctx = ClientSession(self._read, self._write)
        self._session = await session_ctx.__aenter__()

        init_result = await self._session.initialize()
        self.logger.info("Connected to MCP server %s v%s", init_result.serverInfo.name, init_result.serverInfo.version)

        tools_result = await self._session.list_tools()
        self.tools = {tool.name: tool for tool in tools_result.tools}
        self.logger.info("Tools available: %s", list(self.tools.keys()))

    async def disconnect(self) -> None:
        """
        Gracefully shut down the MCP session/subprocess.
        """
        if self._session:
            await self._session.__aexit__(None, None, None)
            self._session = None
        if self._client_ctx:
            await self._client_ctx.__aexit__(None, None, None)
            self._client_ctx = None
        self.logger.info("Disconnected from MCP server")

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a tool and return a structured result.
        """
        if not self._session:
            raise RuntimeError("MCP session not connected")

        self.logger.info("Calling tool %s with args %s", name, arguments)
        result = await self._session.call_tool(name, arguments)

        text_chunks: List[str] = []
        for item in result.content or []:
            if hasattr(item, "text") and item.text:
                text_chunks.append(item.text)
        raw = "".join(text_chunks).strip()

        parsed: Any
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = raw

        payload = {
            "success": not result.isError,
            "is_error": result.isError,
            "raw": raw,
            "data": parsed,
        }
        # Persist full tool payloads separately for debugging.
        try:
            serialized = json.dumps(payload, ensure_ascii=False)
        except TypeError:
            serialized = str(payload)
        self.tool_result_logger.info("%s args=%s result=%s", name, arguments, serialized)
        self.logger.info("Tool %s complete (success=%s)", name, payload["success"])
        return payload
