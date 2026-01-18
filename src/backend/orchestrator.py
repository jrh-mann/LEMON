"""Orchestrator for tool-based CLI use."""

from __future__ import annotations

from dataclasses import dataclass
import os
import json
import logging
from typing import Any, Callable, Dict, List, Optional

from .tools import ToolRegistry
from .mcp_client import call_mcp_tool
from .llm import call_llm_stream, call_llm_with_tools


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
        self._use_mcp = os.environ.get("LEMON_USE_MCP", "").lower() not in {"0", "false", "no"}

    def run_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        *,
        stream: Optional[Callable[[str], None]] = None,
    ) -> ToolResult:
        self._logger.info("Running tool name=%s args_keys=%s", tool_name, sorted(args.keys()))
        self._tool_logger.info(
            "tool_request name=%s args=%s",
            tool_name,
            json.dumps(args, ensure_ascii=True),
        )
        if self._use_mcp:
            data = call_mcp_tool(tool_name, args)
        else:
            data = self.tools.execute(tool_name, args, stream=stream)
        self._tool_logger.info(
            "tool_response name=%s data=%s",
            tool_name,
            json.dumps(data, ensure_ascii=True),
        )
        return ToolResult(tool=tool_name, data=data)

    def respond(
        self,
        user_message: str,
        *,
        image_name: Optional[str] = None,
        has_image: bool = False,
        stream: Optional[Callable[[str], None]] = None,
        allow_tools: bool = True,
        on_tool_event: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
    ) -> str:
        """Respond to a user message, optionally calling tools."""
        self._logger.info("Received message bytes=%d", len(user_message.encode("utf-8")))
        tool_desc = [
            {
                "type": "function",
                "function": {
                    "name": "analyze_workflow",
                    "description": (
                        "Analyze the most recently uploaded workflow image. "
                        "Returns JSON with inputs, outputs, tree, doubts, plus session_id. "
                        "Use session_id + feedback to refine a prior analysis. "
                        "If no image has been uploaded, the tool will report that."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "Optional session id to continue a prior analysis.",
                            },
                            "feedback": {
                                "type": "string",
                                "description": "Optional feedback to refine the analysis.",
                            },
                        },
                        "required": [],
                    },
                },
            }
        ]

        system = (
            "You are the orchestrator for a system that ingests flowchart images "
            "and converts them into structured data, ultimately used to generate "
            "Python programs. Mission: help users understand, refine, and evolve "
            "their flowcharts; be proactive and helpful; only perform analysis or "
            "modifications through tools when explicitly requested or confirmed. "
            "Core rules: do not edit JSON directly; all changes go through tool "
            "calls. Prefer clarifying questions before any modification to the "
            "JSON/tree. If the user explicitly requests analysis of an image, tell the user what ur doing and then call "
            "the tool. Clarifying questions are allowed "
            "without tool use. "
            "Tool use policy: tools are required for analyzing a new image or "
            "applying JSON/tree changes. Tool calls are executed via MCP. Use tools "
            "when needed, but you may respond in plain text for discussion and guidance. "
            "After tool results are provided, respond in plain text only; do not request "
            "additional tool calls unless required. Do not show raw tool JSON to the user; summarize "
            "ONLY inputs, outputs, and doubts from the tool result. Tool output may "
            "omit the tree; state what is missing and ask how to proceed. "
            "Decision flow: if the user explicitly says analyze [image_name], apply "
            "changes, add/update/remove node, modify/merge/reorder/connect, generate "
            "structured data, or similar, call the tool. If ambiguous, ask "
            "clarifying questions first. For discussion, reviews, explanations, "
            "planning, proposing edits, or best-practice advice, stay in plain text "
            "and do not call tools. Clarifying questions before action: for edits, "
            "confirm exact nodes/branches, desired outcome, acceptance criteria, "
            "and whether minor or major. For continued sessions, ask for or reuse "
            "session_id and request feedback instead of re-running image analysis. "
            "Interaction style: concise, friendly, solution-oriented; offer options "
            "with pros/cons; suggest validation steps without calling tools unless "
            "requested. Formatting: avoid heavy formatting; bullets are fine; keep "
            "outputs machine-parseable when emitting tool JSON; otherwise plain "
            "text. Error handling: if a tool fails or returns incomplete data, "
            "explain what is missing, propose remedies, ask how to proceed; if the "
            "user says don't call tools, stay in plain text unless they reverse it."
        )
        if self.last_session_id:
            system += f" Current analyze_workflow session_id: {self.last_session_id}."
        if has_image:
            system += (
                " The user has uploaded an image; analyze_workflow will use the latest upload."
            )
        if not allow_tools:
            system += (
                " Tools are disabled for this response. Do NOT call tools; respond in "
                "plain text only."
            )

        messages = [
            {"role": "system", "content": system},
            *self.history,
            {"role": "user", "content": user_message},
        ]
        did_stream = False
        try:
            def on_delta(delta: str) -> None:
                nonlocal did_stream
                did_stream = True
                if stream:
                    stream(delta)

            if allow_tools:
                raw, tool_calls = call_llm_with_tools(
                    messages,
                    tools=tool_desc,
                    tool_choice=None,
                    on_delta=on_delta if stream else None,
                )
            else:
                if stream:
                    raw = call_llm_stream(
                        messages,
                        on_delta=on_delta,
                    )
                    raw = raw.strip()
                    tool_calls = []
                else:
                    raw, tool_calls = call_llm_with_tools(
                        messages,
                        tools=None,
                        tool_choice="none",
                    )
        except Exception as exc:
            self._logger.exception("LLM error while responding")
            return f"LLM error: {exc}"

        tool_iterations = 0
        tool_results: List[ToolResult] = []
        while allow_tools and tool_calls:
            tool_iterations += 1
            if tool_iterations > 5:
                return "Tool error (max tool calls reached)."

            messages.append(
                {
                    "role": "assistant",
                    "content": raw or "",
                    "tool_calls": tool_calls,
                }
            )

            for call in tool_calls:
                fn = call.get("function") or {}
                tool_name = fn.get("name")
                args_text = fn.get("arguments") or "{}"
                if isinstance(args_text, str):
                    try:
                        args = json.loads(args_text)
                    except json.JSONDecodeError:
                        args = {}
                elif isinstance(args_text, dict):
                    args = args_text
                else:
                    args = {}
                try:
                    if on_tool_event:
                        on_tool_event("tool_start", tool_name, args)
                    result = self.run_tool(tool_name, args, stream=None)
                    session_id = result.data.get("session_id")
                    if session_id:
                        self.last_session_id = session_id
                    tool_results.append(result)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id"),
                            "content": json.dumps(result.data),
                        }
                    )
                    if on_tool_event:
                        on_tool_event("tool_complete", tool_name, args)
                except Exception as exc:
                    self._tool_logger.error(
                        "tool_error name=%s error=%s",
                        tool_name,
                        str(exc),
                    )
                    return f"Tool error ({tool_name}): {exc}"

            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Tool execution succeeded. The tool results are provided above. "
                        "Respond in plain text only, summarizing inputs, outputs, and doubts."
                    ),
                }
            )
            raw, tool_calls = call_llm_with_tools(
                messages,
                tools=tool_desc,
                tool_choice="none",
            )

        final_text = raw or (_summarize_tool_results(tool_results) if tool_results else "")
        if stream:
            if tool_results and final_text:
                _emit_stream(stream, final_text)
            elif not did_stream:
                _emit_stream(stream, final_text)
        self.history.append({"role": "user", "content": user_message})
        self.history.append({"role": "assistant", "content": final_text})
        return final_text



def _emit_stream(stream: Callable[[str], None], text: str, *, chunk_size: int = 800) -> None:
    if not text:
        return
    for idx in range(0, len(text), chunk_size):
        stream(text[idx : idx + chunk_size])


def _summarize_tool_results(results: List[ToolResult]) -> str:
    parts: List[str] = []
    for result in results:
        analysis = result.data.get("analysis") if isinstance(result.data, dict) else {}
        if not isinstance(analysis, dict):
            analysis = {}
        inputs = analysis.get("inputs") if isinstance(analysis.get("inputs"), list) else []
        outputs = analysis.get("outputs") if isinstance(analysis.get("outputs"), list) else []
        doubts = analysis.get("doubts") if isinstance(analysis.get("doubts"), list) else []

        def _fmt_items(items: list, key: str) -> str:
            lines = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or item.get(key) or ""
                typ = item.get("type")
                if typ:
                    lines.append(f"- {name} ({typ})")
                else:
                    lines.append(f"- {name}")
            return "\n".join(lines) if lines else "- None"

        inputs_text = _fmt_items(inputs, "input")
        outputs_text = _fmt_items(outputs, "output")
        doubts_text = "\n".join(f"- {d}" for d in doubts) if doubts else "- None"
        header = f"Analysis complete ({result.tool})." if len(results) > 1 else "Analysis complete."
        parts.append(
            f"{header}\n\n"
            "Inputs:\n"
            f"{inputs_text}\n\n"
            "Outputs:\n"
            f"{outputs_text}\n\n"
            "Doubts:\n"
            f"{doubts_text}"
        )
    return "\n\n".join(parts)
