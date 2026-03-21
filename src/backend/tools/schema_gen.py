"""Auto-generate Anthropic tool schemas from registered Tool classes.

Replaces the hand-maintained tool_schemas.py. Each tool's schema is
produced by ``Tool.to_anthropic_schema()`` which reads the tool's
``name``, ``description``, ``parameters``, and optional
``_schema_override`` to build the JSON expected by the Anthropic API.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .core import ToolRegistry


def generate_all_schemas(registry: ToolRegistry) -> List[Dict[str, Any]]:
    """Generate Anthropic tool schemas from all registered tools.

    Args:
        registry: The ToolRegistry containing all tool instances.

    Returns:
        List of tool schema dicts in Anthropic function-calling format.
    """
    return [tool.to_anthropic_schema() for tool in registry.all_tools()]
