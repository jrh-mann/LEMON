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
    ) -> Dict[str, Any]:
        """Analyze a workflow image and return a JSON report."""
        self._logger.info(
            "Subagent analyze session_id=%s image=%s feedback=%s",
            session_id,
            image_path.name,
            bool(feedback),
        )
        prompt = """Analyze this workflow diagram image.

Return ONLY a JSON object with this structure:
{
  "inputs": [
    {"id": "input_name_type", "name": "...", "type": "int|float|bool|string|enum|date", "description": "..."}
  ],
  "outputs": [
    {"name": "...", "description": "..."}
  ],
  "tree": {
    "start": {
      "id": "start",
      "type": "start",
      "label": "exact text from diagram",
      "children": [
        {
          "id": "n1",
          "type": "decision|action|output",
          "label": "exact text from diagram",
          "input_ids": ["input_name_type"],
          "edge_label": "Yes|No|optional",
          "children": [ ... ]
        }
      ]
    }
  },
  "doubts": [
    "question or ambiguity 1",
    "question or ambiguity 2"
  ]
}

Rules:
- Use exact text from the diagram.
- If there are no doubts, return "doubts": [].
- Every input must include an "id" computed as: input_{slug(name)}_{type}
  - slug: lowercase, replace non-alphanumeric with underscores, collapse repeats.
- If a decision/action depends on one or more inputs, include "input_ids" on that node
  referencing the input ids.
- Tree rules:
  - This must be a single rooted tree starting at tree.start.
  - Allowed node types: start, decision, action, output.
  - Outputs MUST be leaf nodes (no children).
  - edge_label is required when the diagram shows branch labels (Yes/No); otherwise omit or set to "".
  - Every node id must be unique across the tree.
- Return JSON only, no extra text.

Once you've received clarifications via feedback, adjust the analysis accordingly, preserving ids
by recomputing them deterministically from name + type. Respond only with the updated JSON object.
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
            ).strip()
        else:
            raw = call_llm(
                messages,
                max_completion_tokens=60000,
                response_format=None,
                caller="subagent",
                request_tag="analyze",
            ).strip()
        llm_ms = (time.perf_counter() - llm_start) * 1000
        self._logger.info("LLM call complete session_id=%s ms=%.1f", session_id, llm_ms)
        if not raw:
            raise ValueError("LLM returned an empty response.")

        if is_followup and not wants_json:
            return {"message": raw}

        data = self._parse_json(raw, prompt, history_messages, system_msg, user_msg)
        data = normalize_analysis(data)

        # Persist conversation history for continuity.
        if not is_followup:
            self.history.add_message(session_id, "user", prompt)
        if feedback:
            self.history.add_message(session_id, "user", feedback)
        self.history.add_message(session_id, "assistant", json.dumps(data))
        self.history.store_analysis(session_id, data)
        return data


def _wants_json(feedback: str) -> bool:
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


    def _parse_json(
        self,
        raw: str,
        prompt: str,
        history_messages: list[dict],
        system_msg: dict,
        user_msg: dict,
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
        retry_raw = call_llm(
            retry_messages,
            max_completion_tokens=60000,
            response_format=None,
            caller="subagent",
            request_tag="json_retry",
        ).strip()
        if not retry_raw:
            raise ValueError("LLM returned an empty response on retry.")
        parsed_retry = _try_parse(retry_raw)
        if parsed_retry is not None:
            return parsed_retry
        self._logger.error("Retry JSON parse failed")
        raise ValueError(f"Invalid JSON from LLM: {retry_raw}")
