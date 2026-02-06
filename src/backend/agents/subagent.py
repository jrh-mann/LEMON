"""Sub-agent that analyzes workflow images."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Callable, Dict, Optional

from ..storage.history import HistoryStore
from ..llm import call_llm, call_llm_stream
from ..utils.image import image_to_data_url
from ..utils.analysis import normalize_analysis
from ..utils.cancellation import CancellationError


class Subagent:
    """Stateful subagent with persisted chat history."""

    def __init__(self, history: HistoryStore):
        self.history = history
        self._logger = logging.getLogger("backend.subagent")

    def analyze(
        self,
        *,
        image_path: Path,
        session_id: str,
        feedback: Optional[str] = None,
        stream: Optional[Callable[[str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """Analyze a workflow image and return a JSON report."""
        self._logger.info(
            "Subagent analyze session_id=%s image=%s feedback=%s",
            session_id,
            image_path.name,
            bool(feedback),
        )
        def is_cancelled() -> bool:
            return bool(should_cancel and should_cancel())
        if is_cancelled():
            raise CancellationError("Subagent cancelled before analysis.")
        # v12 prompt: Reverts v11's harmful "exact diagram text" variable naming
        # (which caused QRISK/LDL variables to go missing). Keeps v11's multi-way
        # split example and every-node-once rule. Adds clearer variable naming
        # guidance: use the CONCEPT being evaluated, not the full node label.
        prompt = """Analyze this workflow diagram image. Return ONLY a JSON object.

Before writing JSON, mentally: (1) trace every arrow noting arrowhead direction — arrows
can point up/down/left/right, do NOT assume top-to-bottom flow, (2) identify the entry
point — the node with NO incoming arrows from other decision/action nodes, (3) list all
numeric thresholds from edge labels.

{
  "inputs": [
    {"id": "input_name_type", "name": "...", "type": "int|float|bool|string|enum|date", "description": "..."}
  ],
  "outputs": [
    {"name": "...", "description": "..."}
  ],
  "tree": {
    "start": {
      "id": "start", "type": "start", "label": "Start",
      "children": [{
        "id": "n1", "type": "decision", "label": "exact text from diagram",
        "input_ids": ["input_name_type"],
        "edge_label": "label from arrow",
        "condition": {"input_id": "input_name_type", "comparator": "gte|gt|lte|lt|eq|enum_eq|is_true|is_false", "value": 0},
        "children": [{"id": "n2", "type": "output", "label": "exact text", "edge_label": "Yes", "children": []}]
      }]
    }
  },
  "doubts": ["ambiguity 1"]
}

Rules:

Inputs:
- Each input is a variable the workflow evaluates. ID format: input_{slug(name)}_{type}.
- Name each input using the CONCEPT being evaluated, not the full node label
  (e.g., node "Assess Total Cholesterol Result" → name: "Total Cholesterol";
   node "Calculate QRISK2/3" → name: "QRISK2/3 Score").
- Declare every variable used in any decision condition.

Outputs:
- Every node with NO outgoing arrows is a terminal output.
- outputs array and tree leaf nodes must match one-to-one.
- The outputs array is a deduplicated set of unique endpoint actions. If the same
  action appears at multiple tree locations, list it once. Use exact diagram text
  for names — never append parenthetical qualifiers or path context.
- Only include nodes that are part of the decision flow. Informational side panels,
  annotations, and reference boxes are not outputs.

Node types:
- "decision": 2+ outgoing arrows. MUST have "condition". Even if labelled "Calculate" or
  "Assess", if it branches it is a decision.
- "action": exactly 1 outgoing arrow to further steps. If a node has an outgoing arrow
  to another node, it is NOT an output — it is an action (1 arrow) or decision (2+ arrows).
- "output": NO outgoing arrows. Must have children: [].

Conditions:
- "comparator": one of gte, gt, lte, lt, eq, enum_eq, is_true, is_false.
- Read the comparison operator from edge labels EXACTLY: "≤" means lte, "<" means lt,
  "≥" means gte, ">" means gt. Do not approximate — ≤ and < are different operators.
- For 3+ branches from one node, chain binary decisions. Split on the LOWEST boundary
  first, then split the remainder into a second decision.
  Example: edges "LDL ≤2", "LDL 2-2.5", "LDL ≥2.6" →
    decision(lte 2) → [child "≤2", decision(gte 2.6) → [child "≥2.6", child "2-2.5"]]

Tree:
- Entry point (first child of Start) = node with NO incoming arrows from other nodes.
  Trace arrowheads, not visual position or layout.
- EVERY node in the diagram must appear EXACTLY ONCE in the tree. Do not skip nodes and
  do not duplicate them. Follow every outgoing arrow from each node to find its children.
- Loops: represent the loop-back point as an output node, note in doubts.
- edge_label: exact text from the diagram's arrows.
- Use exact label text from the diagram for node labels. Every node id must be unique.

Return JSON only, no extra text.
"""

        history_messages = [
            {"role": m.role, "content": m.content} for m in self.history.list_messages(session_id)
        ]
        self._logger.debug(
            "Loaded history messages session_id=%s count=%d",
            session_id,
            len(history_messages),
        )
        is_followup = bool(history_messages) and bool(feedback)
        self._logger.debug("Followup mode=%s", is_followup)

        system_msg = {
            "role": "system",
            "content": "You extract structured data from workflow images.",
        }
        wants_json = _wants_json(feedback or "")
        if is_followup:
            user_msg = {
                "role": "user",
                "content": (
                    "You are in a follow-up discussion. Answer the user's question plainly. "
                    "Do NOT return JSON unless the user explicitly asks to regenerate the full JSON. "
                    "If the user asks for regeneration, return ONLY the full JSON object in the original format.\n\n"
                    f"User feedback: {feedback}"
                ),
            }
        else:
            encode_start = time.perf_counter()
            data_url = image_to_data_url(image_path)
            encode_ms = (time.perf_counter() - encode_start) * 1000
            self._logger.info(
                "Image encoded session_id=%s ms=%.1f size_bytes=%d",
                session_id,
                encode_ms,
                len(data_url.encode("utf-8")),
            )
            user_msg = {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        messages = [system_msg, *history_messages, user_msg]

        llm_start = time.perf_counter()
        force_stream = os.environ.get("LEMON_SUBAGENT_STREAM", "").lower() in {"1", "true", "yes"}
        should_stream = stream is not None or force_stream
        if should_stream:
            total_chars = 0
            last_log = time.perf_counter()

            def on_delta(chunk: str) -> None:
                nonlocal total_chars, last_log
                if is_cancelled():
                    raise CancellationError("Subagent cancelled while streaming.")
                total_chars += len(chunk)
                now = time.perf_counter()
                if now - last_log >= 1.0:
                    self._logger.info("Subagent streaming... chars=%d", total_chars)
                    last_log = now
                if stream:
                    stream(chunk)

            raw = call_llm_stream(
                messages,
                max_completion_tokens=60000,
                response_format=None,
                on_delta=on_delta,
                caller="subagent",
                request_tag="analyze_stream",
                should_cancel=should_cancel,
            ).strip()
        else:
            raw = call_llm(
                messages,
                max_completion_tokens=60000,
                response_format=None,
                caller="subagent",
                request_tag="analyze",
                should_cancel=should_cancel,
            ).strip()
        llm_ms = (time.perf_counter() - llm_start) * 1000
        self._logger.info("LLM call complete session_id=%s ms=%.1f", session_id, llm_ms)
        if is_cancelled():
            raise CancellationError("Subagent cancelled after LLM call.")
        if not raw:
            raise ValueError("LLM returned an empty response.")

        if is_followup and not wants_json:
            return {"message": raw}

        data = self._parse_json(raw, prompt, history_messages, system_msg, user_msg, should_cancel=should_cancel)
        data = normalize_analysis(data)
        if is_cancelled():
            raise CancellationError("Subagent cancelled before persisting history.")

        # Persist conversation history for continuity.
        if not is_followup:
            self.history.add_message(session_id, "user", prompt)
        if feedback:
            self.history.add_message(session_id, "user", feedback)
        self.history.add_message(session_id, "assistant", json.dumps(data))
        self.history.store_analysis(session_id, data)
        return data

    def _parse_json(
        self,
        raw: str,
        prompt: str,
        history_messages: list[dict],
        system_msg: dict,
        user_msg: dict,
        *,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        def _strip_code_fences(text: str) -> str:
            stripped = text.strip()
            if stripped.startswith("```") and stripped.endswith("```"):
                stripped = stripped.strip("`").strip()
                if stripped.lower().startswith("json"):
                    stripped = stripped[4:].strip()
            return stripped

        def _try_parse(text: str) -> Dict[str, Any] | None:
            cleaned = _strip_code_fences(text)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass
            start = cleaned.find("{")
            if start == -1:
                return None
            try:
                obj, _ = json.JSONDecoder().raw_decode(cleaned[start:])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                return None
            return None

        parsed = _try_parse(raw)
        if parsed is not None:
            return parsed
        self._logger.warning("Initial JSON parse failed, attempting recovery")

        # Retry with stricter JSON-only instruction.
        retry_messages = [
            system_msg,
            *history_messages,
            user_msg,
            {"role": "user", "content": "Return ONLY valid JSON. No extra text."},
        ]
        if should_cancel and should_cancel():
            raise CancellationError("Subagent cancelled before JSON retry.")
        retry_raw = call_llm(
            retry_messages,
            max_completion_tokens=60000,
            response_format=None,
            caller="subagent",
            request_tag="json_retry",
            should_cancel=should_cancel,
        ).strip()
        if not retry_raw:
            raise ValueError("LLM returned an empty response on retry.")
        parsed_retry = _try_parse(retry_raw)
        if parsed_retry is not None:
            return parsed_retry
        self._logger.error("Retry JSON parse failed")
        raise ValueError(f"Invalid JSON from LLM: {retry_raw}")


def _wants_json(feedback: str) -> bool:
    """
    Helper function to determine if feedback requests JSON output.

    Returns True if feedback contains keywords indicating the user wants
    JSON regeneration rather than a conversational response.
    """
    text = feedback.lower()
    triggers = (
        "regenerate json",
        "return json",
        "full json",
        "output json",
        "produce json",
        "updated json",
        "json object",
    )
    return any(t in text for t in triggers)
