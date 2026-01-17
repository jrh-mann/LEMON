"""Sub-agent that analyzes workflow images."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from .history import HistoryStore
from .llm import call_azure_openai
from .utils import image_to_data_url


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
    {"name": "...", "type": "int|float|bool|string|enum|date", "description": "..."}
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
- Tree rules:
  - This must be a single rooted tree starting at tree.start.
  - Allowed node types: start, decision, action, output.
  - Outputs MUST be leaf nodes (no children).
  - edge_label is required when the diagram shows branch labels (Yes/No); otherwise omit or set to "".
  - Every node id must be unique across the tree.
- Return JSON only, no extra text.
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
        if is_followup:
            user_msg = {"role": "user", "content": feedback}
        else:
            data_url = image_to_data_url(image_path)
            user_msg = {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        messages = [system_msg, *history_messages, user_msg]

        raw = call_azure_openai(
            messages,
            max_completion_tokens=60000,
            response_format=None,
        ).strip()
        if not raw:
            raise ValueError("LLM returned an empty response.")

        data = self._parse_json(raw, prompt, history_messages, system_msg, user_msg)

        # Persist conversation history for continuity.
        if not is_followup:
            self.history.add_message(session_id, "user", prompt)
        if feedback:
            self.history.add_message(session_id, "user", feedback)
        self.history.add_message(session_id, "assistant", json.dumps(data))
        return data

    def _parse_json(
        self,
        raw: str,
        prompt: str,
        history_messages: list[dict],
        system_msg: dict,
        user_msg: dict,
    ) -> Dict[str, Any]:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            self._logger.warning("Initial JSON parse failed, attempting recovery")
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(raw[start : end + 1])

            # Retry with stricter JSON-only instruction.
            retry_messages = [
                system_msg,
                *history_messages,
                user_msg,
                {"role": "user", "content": "Return ONLY valid JSON. No extra text."},
            ]
            retry_raw = call_azure_openai(
                retry_messages,
                max_completion_tokens=60000,
                response_format=None,
            ).strip()
            if not retry_raw:
                raise ValueError("LLM returned an empty response on retry.")
            try:
                return json.loads(retry_raw)
            except json.JSONDecodeError:
                self._logger.error("Retry JSON parse failed")
                start = retry_raw.find("{")
                end = retry_raw.rfind("}")
                if start != -1 and end != -1 and end > start:
                    return json.loads(retry_raw[start : end + 1])
                raise ValueError(f"Invalid JSON from LLM: {retry_raw}")
