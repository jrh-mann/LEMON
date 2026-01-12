"""Orchestrator agent for reactive tool selection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.utils.request_utils import make_request

from ..utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class OrchestratorDecision:
    action: str
    assistant_message: str


class OrchestratorAgent:
    """Decide which pipeline tool to run based on the chat context."""

    def __init__(self, *, max_tokens: int = 800, model: Optional[str] = None):
        self.max_tokens = max_tokens
        self.model = model

    def decide(
        self,
        *,
        conversation: List[Dict[str, str]],
        state_summary: Dict[str, Any],
    ) -> OrchestratorDecision:
        prompt = _build_prompt(conversation=conversation, state_summary=state_summary)
        response = make_request(
            [{"role": "user", "content": prompt}],
            max_tokens=self.max_tokens,
            model=self.model,
            system=ORCHESTRATOR_SYSTEM_PROMPT,
            response_format={"type": "json_object"},
        )
        text = response.content[0].text if response.content else ""
        decision = _parse_decision(text)
        if decision is None:
            logger.warning("Orchestrator returned invalid JSON", extra={"raw": text})
            fallback = _fallback_decision(conversation=conversation, state_summary=state_summary)
            if fallback:
                return fallback
            return OrchestratorDecision(
                action="help",
                assistant_message=(
                    "I can analyze the workflow, update the flowchart, run refinement, or "
                    "share status. Tell me which step to run."
                ),
            )
        return decision


def _build_prompt(
    *, conversation: List[Dict[str, str]], state_summary: Dict[str, Any]
) -> str:
    lines: List[str] = []
    lines.append("TOOLS:")
    lines.append("- analyze: Analyze the workflow image and extract inputs/outputs.")
    lines.append("- refine: Generate tests and run the refinement loop.")
    lines.append("- flowchart: Update the flowchart from a natural-language request.")
    lines.append("- status: Summarize current progress.")
    lines.append("- help: Explain what you can do.")
    lines.append("- none: No tool call.")
    lines.append("")
    lines.append("STATE:")
    for key, value in state_summary.items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("CONVERSATION (most recent last):")
    for msg in conversation:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        lines.append(f"{role}: {content}")
    lines.append("")
    lines.append(
        "Return JSON only with keys: action (analyze|refine|flowchart|status|help|none) and "
        "assistant_message. Choose a tool only when the user explicitly asks."
    )
    return "\n".join(lines)


def _parse_decision(text: str) -> Optional[OrchestratorDecision]:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    action = str(data.get("action", "none")).strip().lower()
    assistant_message = str(data.get("assistant_message", "")).strip()
    if not assistant_message:
        assistant_message = "OK."
    return OrchestratorDecision(action=action, assistant_message=assistant_message)


def _fallback_decision(
    *, conversation: List[Dict[str, str]], state_summary: Dict[str, Any]
) -> Optional[OrchestratorDecision]:
    if not conversation:
        return None
    last = conversation[-1].get("content", "").lower()
    if not last:
        return None

    if any(word in last for word in ["status", "progress", "update"]):
        return OrchestratorDecision(action="status", assistant_message="Checking status.")
    if any(word in last for word in ["analyze", "analysis", "review"]):
        return OrchestratorDecision(action="analyze", assistant_message="Starting analysis.")
    if any(word in last for word in ["refine", "refinement", "run tests", "generate code"]):
        return OrchestratorDecision(action="refine", assistant_message="Starting refinement.")
    if any(word in last for word in ["flowchart", "diagram", "canvas", "node", "edge", "connect"]):
        return OrchestratorDecision(action="flowchart", assistant_message="Updating flowchart.")

    return None


ORCHESTRATOR_SYSTEM_PROMPT = (
    "You are an orchestrator for a workflow-to-code pipeline. "
    "You decide which tool to run based on user requests, including flowchart edits. "
    "Be reactive: only call tools when explicitly asked. "
    "Always return JSON only."
)
