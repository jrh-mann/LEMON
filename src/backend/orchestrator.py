"""Orchestrator for tool-based CLI use."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from typing import Any, Callable, Dict, List, Optional

from .tools import ToolRegistry
from .llm import call_azure_openai, call_azure_openai_stream


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
        stream: Optional[Callable[[str], None]] = None,
    ) -> str:
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
            "and converts them into structured data, ultimately used to generate "
            "Python programs. Mission: help users understand, refine, and evolve "
            "their flowcharts; be proactive and helpful; only perform analysis or "
            "modifications through tools when explicitly requested or confirmed. "
            "Core rules: do not edit JSON directly; all changes go through tool "
            "calls. Prefer clarifying questions before any modification to the "
            "JSON/tree. If the user explicitly requests analysis of an image, call "
            "the tool without extra clarification. Clarifying questions are allowed "
            "without tool use. Knowledge cutoff: 2024-10. "
            "Tool use policy: tools are required for analyzing a new image or "
            "applying JSON/tree changes. When a tool is needed, respond ONLY with "
            "a JSON object: {\"tool\": \"name\", \"args\": {...}}. If no tool is "
            "needed, respond in plain text. After tool results are provided, respond "
            "in plain text only; do not emit additional tool JSON unless another "
            "tool call is required. Do not show raw tool JSON to the user; summarize "
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
            # Do not stream tool-selection output.
            raw = call_azure_openai(messages)
        except Exception as exc:
            self._logger.exception("LLM error while responding")
            return f"LLM error: {exc}"

        # Try tool-call JSON first.
        tool_iterations = 0
        tool_results: List[ToolResult] = []
        while True:
            payload = _extract_tool_payload(raw)
            if payload is None:
                break

            tool_name = payload.get("tool")
            args = payload.get("args") or {}
            tool_iterations += 1
            if tool_iterations > 5:
                return "Tool error (max tool calls reached)."
            try:
                # Do not stream tool output; only stream the final summary.
                result = self.run_tool(tool_name, args, stream=None)
                session_id = result.data.get("session_id")
                if session_id:
                    self.last_session_id = session_id
                tool_results.append(result)
                tool_payload = {
                    "source": "subagent",
                    "tool": tool_name,
                    "data": result.data,
                }
                tool_text = json.dumps(tool_payload, indent=2)
                messages.append({"role": "assistant", "content": tool_text})
                raw = call_azure_openai(messages)
                continue
            except Exception as exc:
                self._tool_logger.error(
                    "tool_error name=%s error=%s",
                    tool_name,
                    str(exc),
                )
                return f"Tool error ({tool_name}): {exc}"

        if tool_results:
            final_text = _summarize_tool_results(tool_results)
        else:
            final_text = raw
        if stream:
            _emit_stream(stream, final_text)
        self.history.append({"role": "user", "content": user_message})
        self.history.append({"role": "assistant", "content": final_text})
        return final_text


def _emit_stream(stream: Callable[[str], None], text: str, *, chunk_size: int = 800) -> None:
    if not text:
        return
    for idx in range(0, len(text), chunk_size):
        stream(text[idx : idx + chunk_size])


def _extract_tool_payload(raw: str) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict) and "tool" in payload:
        return payload
    # Try to salvage a JSON object if the model returned extra text.
    if not raw:
        return None
    if '"tool"' not in raw:
        return None
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    snippet = raw[start : end + 1]
    try:
        payload = json.loads(snippet)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict) and "tool" in payload:
        return payload
    return None


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
