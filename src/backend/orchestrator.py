"""Orchestrator for tool-based CLI use."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from typing import Any, Dict, List, Optional

from .tools import ToolRegistry
from .llm import call_azure_openai


@dataclass
class ToolResult:
    tool: str
    data: Dict[str, Any]


class Orchestrator:
    """Minimal orchestrator that uses the LLM to choose tools."""

    def __init__(self, tools: ToolRegistry):
        self.tools = tools
        self.last_session_id: Optional[str] = None
        self.history: List[Dict[str, str]] = []
        self._logger = logging.getLogger(__name__)
        self._tool_logger = logging.getLogger("backend.tool_calls")

    def run_tool(self, tool_name: str, args: Dict[str, Any]) -> ToolResult:
        self._logger.info("Running tool name=%s args_keys=%s", tool_name, sorted(args.keys()))
        self._tool_logger.info(
            "tool_request name=%s args=%s",
            tool_name,
            json.dumps(args, ensure_ascii=True),
        )
        data = self.tools.execute(tool_name, args)
        self._tool_logger.info(
            "tool_response name=%s data=%s",
            tool_name,
            json.dumps(data, ensure_ascii=True),
        )
        return ToolResult(tool=tool_name, data=data)

    def respond(self, user_message: str, *, image_name: Optional[str] = None) -> str:
        """Respond to a user message, optionally calling tools."""
        self._logger.info("Received message bytes=%d", len(user_message.encode("utf-8")))
        tool_desc = [
            {
                "name": "analyze_workflow",
                "description": (
                    "Analyze a workflow image in repo root. "
                    "Returns JSON with inputs, outputs, tree, doubts, plus session_id. "
                    "Use session_id + feedback to refine a prior analysis."
                ),
                "args": {
                    "image_name": "string (filename in repo root; required on first call)",
                    "session_id": "string (optional, to continue a prior analysis)",
                    "feedback": "string (optional, user feedback to refine analysis)",
                },
            }
        ]

        system = (
            "You are the orchestrator for a system that ingests flowchart images "
            "and converts them into structured data. The end goal is to generate "
            "Python programs from flowcharts. Current workflow: analyze images -> "
            "produce JSON representing inputs/outputs/tree -> later render a visual "
            "tree in a frontend. Users can edit the flowchart themselves or ask the "
            "orchestrator to make changes to the JSON/tree. The orchestrator MUST "
            "not edit JSON directly; it can only request changes via tool calls. "
            "Prefer clarifying questions before modifications. For minor changes, "
            "call MCP tools that add/update/remove specific nodes. For major "
            "changes, call the analysis subagent with clear instructions. "
            "Note: tool output may omit the tree in the payload; handle accordingly. "
            "When a tool is needed, respond ONLY with a JSON object: "
            "{\"tool\": \"name\", \"args\": {...}}. "
            "If no tool is needed, respond with plain text. "
            "Tool outputs are responses from a subagent; do not paraphrase them."
        )
        if image_name:
            system += f" If calling analyze_workflow, use image_name: {image_name}."
        if self.last_session_id:
            system += f" Current analyze_workflow session_id: {self.last_session_id}."

        messages = [
            {"role": "system", "content": system + "\n\nTools:\n" + json.dumps(tool_desc)},
            *self.history,
            {"role": "user", "content": user_message},
        ]

        try:
            raw = call_azure_openai(messages)
        except Exception as exc:
            self._logger.exception("LLM error while responding")
            return f"LLM error: {exc}"

        # Try tool-call JSON first.
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict) and "tool" in payload:
                tool_name = payload.get("tool")
                args = payload.get("args") or {}
                try:
                    result = self.run_tool(tool_name, args)
                    session_id = result.data.get("session_id")
                    if session_id:
                        self.last_session_id = session_id
                    assistant_reply = json.dumps(
                        {
                            "source": "subagent",
                            "tool": tool_name,
                            "data": result.data,
                        },
                        indent=2,
                    )
                    self.history.append({"role": "user", "content": user_message})
                    self.history.append({"role": "assistant", "content": assistant_reply})
                    return assistant_reply
                except Exception as exc:
                    self._tool_logger.error(
                        "tool_error name=%s error=%s",
                        tool_name,
                        str(exc),
                    )
                    return f"Tool error ({tool_name}): {exc}"
        except json.JSONDecodeError:
            pass

        self.history.append({"role": "user", "content": user_message})
        self.history.append({"role": "assistant", "content": raw})
        return raw
