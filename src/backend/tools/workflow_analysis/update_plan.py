"""Tool for updating the extraction plan shown to the user.

The orchestrator calls this to display a checklist of planned steps
in the frontend sidebar. The socket event carries the data to the UI.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..core import Tool, ToolParameter


class UpdatePlanTool(Tool):
    """Update the plan checklist shown to the user during workflow extraction."""

    name = "update_plan"
    category = "workflow_analysis"
    prompt_hint = ""
    description = (
        "Update the step-by-step plan shown to the user. Call this to outline "
        "what you see in the image and mark items as done as you build the workflow."
    )
    parameters = [
        ToolParameter(
            name="items",
            type="array",
            description=(
                "List of plan items. Each item has 'text' (string) and 'done' (boolean)."
            ),
            required=True,
            schema_override={
                "type": "array",
                "description": "List of plan items to display.",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Description of this plan step.",
                        },
                        "done": {
                            "type": "boolean",
                            "description": "Whether this step is completed.",
                        },
                    },
                    "required": ["text", "done"],
                },
            },
        ),
    ]

    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        items = args.get("items", [])
        if not isinstance(items, list):
            return {"success": False, "error": "items must be a list"}

        self._logger.info("UpdatePlanTool: %d items", len(items))
        return {
            "success": True,
            "action": "plan_updated",
            "items": items,
        }
