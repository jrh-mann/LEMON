"""Prompt and tool configuration for the orchestrator."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def tool_descriptions() -> List[Dict[str, Any]]:
    return [
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
        },
        {
            "type": "function",
            "function": {
                "name": "publish_latest_analysis",
                "description": (
                    "Load the most recent workflow analysis and return it for rendering "
                    "on the canvas."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
    ]


def build_system_prompt(
    *,
    last_session_id: Optional[str],
    has_image: bool,
    allow_tools: bool,
) -> str:
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
    if last_session_id:
        system += f" Current analyze_workflow session_id: {last_session_id}."
    if has_image:
        system += " The user has uploaded an image; analyze_workflow will use the latest upload."
    if not allow_tools:
        system += (
            " Tools are disabled for this response. Do NOT call tools; respond in "
            "plain text only."
        )
    return system
