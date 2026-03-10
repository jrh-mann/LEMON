"""Tool for updating the extraction plan shown to the user.

The orchestrator calls this to display a checklist of planned steps
in the frontend sidebar. The socket event carries the data to the UI.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..core import Tool, ToolParameter, tool_error


class UpdatePlanTool(Tool):
    """Update the plan checklist shown to the user during workflow extraction."""

    name = "update_plan"
    description = (
        "Update the step-by-step plan shown to the user. "
        "Call this TWICE: once at the start to outline your DFS plan (Step 3), "
        "and once at the end to mark all items done (Step 8). "
        "Do NOT call after every tool — it interrupts your building flow."
    )
    parameters = [
        ToolParameter(
            name="items",
            type="array",
            description=(
                "List of plan items. Each item has 'text' (string) and 'done' (boolean)."
            ),
            required=True,
        ),
    ]

    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        items = args.get("items", [])
        if not isinstance(items, list):
            return tool_error("items must be a list", "INVALID_ITEMS")

        self._logger.info("UpdatePlanTool: %d items", len(items))
        return {
            "success": True,
            "action": "plan_updated",
            "items": items,
        }
