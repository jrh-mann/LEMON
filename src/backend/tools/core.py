"""Core tool abstractions and registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class ToolParameter:
    name: str
    type: str
    description: str
    required: bool = True


class Tool:
    name: str
    description: str
    parameters: List[ToolParameter]
    # Optional: list of old tool names that should also work
    aliases: List[str] = []

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        raise NotImplementedError


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool under its name and any aliases."""
        self._tools[tool.name] = tool
        # Also register under any aliases for backwards compatibility
        for alias in getattr(tool, 'aliases', []):
            self._tools[alias] = tool

    def execute(self, name: str, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")
        return tool.execute(args, **kwargs)
