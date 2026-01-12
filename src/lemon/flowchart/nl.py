"""Natural language flowchart interpretation."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..utils.logging import get_logger
from .model import Flowchart

logger = get_logger(__name__)

DEBUG_FLOWCHART = os.getenv("LEMON_FLOWCHART_DEBUG") == "1"
SYSTEM_PROMPT = (
    "You are a flowchart assistant. Ask concise clarifying questions when needed, "
    "then return a structured flowchart. Never reveal internal reasoning."
)

CLARIFY_INSTRUCTIONS = """Return ONLY valid JSON with one of these shapes:

1) Clarify:
{
  "status": "clarify",
  "questions": ["Question 1", "Question 2"]
}

2) Ready:
{
  "status": "ready"
}

Rules:
- Ask questions only when required to resolve missing branches or outcomes.
- Keep questions to at most 3.
- If the request is sufficiently specified, return status "ready".
- Output JSON only (no markdown).
"""

GENERATE_INSTRUCTIONS = """Return ONLY valid JSON with this schema:
{
  "nodes": [{"id":"n1","type":"start|process|decision|subprocess|end","label":"...","color":"teal|amber|green|slate|rose|sky"}],
  "edges": [{"from":"n1","to":"n2","label":"Yes"}]
}

Rules:
- Use short labels.
- Types must be one of: start, process, decision, subprocess, end.
- Colors must be one of: teal, amber, green, slate, rose, sky.
- Output JSON only (no markdown).
"""


@dataclass
class ClarificationResult:
    status: str
    questions: List[str] = field(default_factory=list)



def clarify_flowchart_request(
    *,
    prompt: str,
    flowchart: Optional[Dict[str, Any]] = None,
    history: Optional[List[Dict[str, str]]] = None,
) -> ClarificationResult:
    history_text = json.dumps(history or [], indent=2)
    flowchart_text = json.dumps(flowchart or {}, indent=2)

    user_prompt = (
        CLARIFY_INSTRUCTIONS
        + "\n\nCONVERSATION:\n"
        + history_text
        + "\n\nCURRENT FLOWCHART:\n"
        + flowchart_text
        + "\n\nUSER REQUEST:\n"
        + prompt.strip()
    )

    text = ""
    try:
        from src.utils.request_utils import make_request

        response = make_request(
            [{"role": "user", "content": user_prompt}],
            max_tokens=64000,
            system=SYSTEM_PROMPT,
        )
        text = response.content[0].text if response.content else ""
        if DEBUG_FLOWCHART:
            logger.info(
                "Flowchart clarify raw response",
                extra={"response_preview": text[:2000]},
            )
        return parse_clarify_response(text)
    except Exception as exc:
        logger.warning(
            "Clarification failed; using fallback.",
            extra={"error": str(exc), "response_preview": (text or "")[:800]},
        )

    questions = simple_clarification_questions(prompt)
    if questions:
        return ClarificationResult(status="clarify", questions=questions)
    return ClarificationResult(status="ready")



def parse_clarify_response(text: str) -> ClarificationResult:
    data = _extract_json_payload(text)

    if isinstance(data, list):
        questions = [str(q).strip() for q in data if str(q).strip()]
        return ClarificationResult(status="clarify", questions=questions)

    if not isinstance(data, dict):
        raise ValueError("Clarification response was not a JSON object or list")

    status = str(data.get("status", "")).lower()
    questions = [str(q).strip() for q in (data.get("questions") or []) if str(q).strip()]

    if status in {"clarify", "question", "questions"} or questions:
        return ClarificationResult(status="clarify", questions=questions)
    if status in {"ready", "complete", "done"}:
        return ClarificationResult(status="ready")
    raise ValueError("Unrecognized clarification response status")



def generate_flowchart_from_request(
    *,
    prompt: str,
    flowchart: Optional[Dict[str, Any]] = None,
    history: Optional[List[Dict[str, str]]] = None,
) -> Flowchart:
    history_text = json.dumps(history or [], indent=2)
    flowchart_text = json.dumps(flowchart or {}, indent=2)

    user_prompt = (
        GENERATE_INSTRUCTIONS
        + "\n\nCONVERSATION:\n"
        + history_text
        + "\n\nCURRENT FLOWCHART:\n"
        + flowchart_text
        + "\n\nUSER REQUEST:\n"
        + prompt.strip()
    )

    text = ""
    try:
        from src.utils.request_utils import make_request

        response = make_request(
            [{"role": "user", "content": user_prompt}],
            max_tokens=64000,
            system=SYSTEM_PROMPT,
        )
        text = response.content[0].text if response.content else ""
        if DEBUG_FLOWCHART:
            logger.info(
                "Flowchart generate raw response",
                extra={"response_preview": text[:2000]},
            )
        return parse_flowchart_json(text)
    except Exception as exc:
        logger.warning(
            "Flowchart generation failed; using fallback.",
            extra={"error": str(exc), "response_preview": (text or "")[:800]},
        )

    return flowchart_from_steps(prompt)



def parse_flowchart_json(text: str) -> Flowchart:
    data = _extract_json_payload(text)

    if isinstance(data, dict):
        if isinstance(data.get("flowchart"), dict):
            data = data["flowchart"]
        return Flowchart.from_dict(data)

    if isinstance(data, list):
        if all(isinstance(item, dict) for item in data):
            return Flowchart.from_dict({"nodes": data, "edges": []})

    raise ValueError("Flowchart response was not a JSON object")



def simple_clarification_questions(prompt: str) -> List[str]:
    questions: List[str] = []
    if re.search(r"\bif\b", prompt, re.IGNORECASE) and not re.search(
        r"\belse\b", prompt, re.IGNORECASE
    ):
        questions.append("What should happen when the condition is false?")
    if "start" not in prompt.lower():
        questions.append("What is the starting step?")
    if "end" not in prompt.lower() and "finish" not in prompt.lower():
        questions.append("What is the final outcome?")
    return questions[:3]



def flowchart_from_steps(prompt: str) -> Flowchart:
    parts = re.split(r"\s*(?:->|\n)\s*", prompt.strip())
    steps = [part.strip() for part in parts if part.strip()]
    if not steps:
        return Flowchart()

    nodes = []
    edges = []
    for idx, step in enumerate(steps):
        node_id = f"step_{idx + 1}"
        node_type = "process"
        if idx == 0 and re.search(r"\bstart\b", step, re.IGNORECASE):
            node_type = "start"
        if idx == len(steps) - 1 and re.search(r"\bend\b", step, re.IGNORECASE):
            node_type = "end"
        nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "label": step[:60],
                "color": "teal",
            }
        )
        if idx > 0:
            edges.append({"from": f"step_{idx}", "to": node_id, "label": ""})

    return Flowchart.from_dict({"nodes": nodes, "edges": edges})



def _extract_json_payload(text: str) -> Any:
    def _strip_fences(raw: str) -> List[str]:
        blocks = []
        for match in re.finditer(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE):
            blocks.append(match.group(1))
        return blocks

    def _extract_balanced(raw: str, open_ch: str, close_ch: str) -> List[str]:
        payloads: List[str] = []
        depth = 0
        start = None
        in_string = False
        escape = False
        for idx, ch in enumerate(raw):
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == "\"":
                    in_string = False
                continue

            if ch == "\"":
                in_string = True
                continue
            if ch == open_ch:
                if depth == 0:
                    start = idx
                depth += 1
            elif ch == close_ch and depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    payloads.append(raw[start : idx + 1])
                    start = None
        return payloads

    candidates = [text.strip()]
    candidates = _strip_fences(text) + candidates

    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

        for payload in _extract_balanced(candidate, "{", "}"):
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                continue
        for payload in _extract_balanced(candidate, "[", "]"):
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                continue

    raise ValueError("No JSON payload found")
