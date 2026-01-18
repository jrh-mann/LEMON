"""
Bridges Anthropic tool calls to MCP tools.
"""

import json
from typing import Any, Dict, List, Callable, Awaitable

from .mcp_client import McpClient


class ToolBridge:
    """
    Keeps MCP tool metadata and provides callables for the LLM tool use flow.
    """

    def __init__(self, mcp_client: McpClient):
        self.mcp_client = mcp_client
        self._tool_defs: List[Dict[str, Any]] = []

    async def refresh_tools(self) -> None:
        """
        Fetch tool definitions from the MCP server and cache Anthropic-friendly schemas.
        """
        tools = self.mcp_client.tools.values()
        defs: List[Dict[str, Any]] = []
        for tool in tools:
            # tool.inputSchema is already a dict-like object; ensure JSON-serializable
            schema = json.loads(json.dumps(tool.inputSchema))
            defs.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": schema,
                }
            )
        self._tool_defs = defs

    @property
    def anthropic_tools(self) -> List[Dict[str, Any]]:
        return list(self._tool_defs)

    def handler(self, name: str) -> Callable[..., Awaitable[Dict[str, Any]]]:
        async def _run(**kwargs: Any) -> Dict[str, Any]:
            return await self.mcp_client.call_tool(name, kwargs)

        return _run

    def function_map(self) -> Dict[str, Callable[..., Awaitable[Dict[str, Any]]]]:
        return {tool["name"]: self.handler(tool["name"]) for tool in self._tool_defs}
