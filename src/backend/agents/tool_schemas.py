"""Tool schema definitions for the orchestrator.

Auto-generates schemas from Tool class metadata via json_schema().
No manual schema maintenance required — add a Tool subclass and it
appears here automatically.
"""

from __future__ import annotations

from typing import Any, Dict, List


def tool_descriptions() -> List[Dict[str, Any]]:
    """Return the list of tool schemas for the orchestrator.

    Each schema follows the Anthropic tool-calling format with
    type, function name, description, and parameter definitions.
    Schemas are auto-generated from the ``Tool.json_schema()``
    classmethod on every discovered tool.
    """
    from ..tools.discovery import discover_tool_classes

    return [cls.json_schema() for cls in discover_tool_classes()]
