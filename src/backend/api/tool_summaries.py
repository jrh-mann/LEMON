"""Formatting helpers for tool summary messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


TOOL_STATUS_MESSAGES = {
    "analyze_workflow": "Subagent analyzed the workflow.",
    "publish_latest_analysis": "Analysis published to the canvas.",
    "get_current_workflow": "Loaded current workflow state.",
    "add_node": "Added a workflow node.",
    "modify_node": "Updated a workflow node.",
    "delete_node": "Removed a workflow node.",
    "add_connection": "Connections added.",
    "delete_connection": "Connections removed.",
    "batch_edit_workflow": "Applied workflow changes.",
}

TOOL_FAILURE_MESSAGES = {
    "analyze_workflow": "Workflow analysis failed.",
    "publish_latest_analysis": "Publishing analysis failed.",
    "get_current_workflow": "Failed to load workflow state.",
    "add_node": "Failed to add a workflow node.",
    "modify_node": "Failed to update a workflow node.",
    "delete_node": "Failed to remove a workflow node.",
    "add_connection": "Failed to add connections.",
    "delete_connection": "Failed to remove connections.",
    "batch_edit_workflow": "Failed to apply workflow changes.",
}


@dataclass
class ToolSummaryTracker:
    messages: Dict[str, str] = field(default_factory=lambda: dict(TOOL_STATUS_MESSAGES))
    failure_messages: Dict[str, str] = field(default_factory=lambda: dict(TOOL_FAILURE_MESSAGES))
    tool_counts: Dict[str, int] = field(default_factory=dict)
    failure_counts: Dict[str, int] = field(default_factory=dict)
    tool_order: List[str] = field(default_factory=list)

    def note(self, tool_name: str, *, success: bool = True) -> None:
        if not tool_name:
            return
        if tool_name not in self.tool_counts:
            self.tool_counts[tool_name] = 0
            self.tool_order.append(tool_name)
        if success:
            self.tool_counts[tool_name] += 1
        else:
            self.failure_counts[tool_name] = self.failure_counts.get(tool_name, 0) + 1

    def flush(self) -> str:
        if not self.tool_order:
            return ""
        lines: List[str] = []
        for name in self.tool_order:
            failure_count = self.failure_counts.get(name, 0)
            if failure_count:
                base = self.failure_messages.get(name, f"Tool failed: {name}.")
                if failure_count > 1:
                    base = base.rstrip(".")
                    base = f"{base} x{failure_count}."
                lines.append(f"> {base}")
            count = self.tool_counts.get(name, 0)
            if count <= 0:
                continue
            base = self.messages.get(name, f"Completed: {name}.")
            if count > 1:
                base = base.rstrip(".")
                base = f"{base} x{count}."
            lines.append(f"> {base}")
        self.tool_counts.clear()
        self.failure_counts.clear()
        self.tool_order.clear()
        if not lines:
            return ""
        return "\n\n" + "\n".join(lines) + "\n\n"
