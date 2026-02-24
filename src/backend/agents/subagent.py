"""Sub-agent that analyzes workflow images."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Callable, Dict, List, Optional

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
        annotations: Optional[List[Dict[str, Any]]] = None,
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
    {
      "x": 120,
      "y": 300,
      "question": "question or ambiguity related to this specific location"
    }
  ]
}

Rules:
- Use exact text from the diagram.
- If there are no doubts, return "doubts": [].
- Every input must include an "id" computed as: input_{slug(name)}_{type}
  - slug: lowercase, replace non-alphanumeric with underscores, collapse repeats.
- Input "name" should be canonical and reusable (short snake_case concept), not a long sentence.
  Example: "A1c after metformin" -> "a1c_after_metformin".
- If a decision/action depends on one or more inputs, include "input_ids" on that node
  referencing the input ids.
- Every DECISION node MUST include a structured "condition" object:
  {"input_id": "...", "comparator": "...", "value": ..., "value2": ... optional}
  - int/float comparators: eq, neq, lt, lte, gt, gte, within_range
  - bool comparators: is_true, is_false
  - string comparators: str_eq, str_neq, str_contains, str_starts_with, str_ends_with
  - enum comparators: enum_eq, enum_neq
  - date comparators: date_eq, date_before, date_after, date_between
- For binary branches, set child edge_label to EXACTLY "true" or "false".
  Do not use "Yes"/"No" in output JSON.
- Tree rules:
  - This must be a single rooted tree starting at tree.start.
  - Allowed node types: start, decision, action, output.
  - Only decision nodes may have multiple children. Action/start nodes must have at most one child. Outputs have no children.
  - Outputs MUST be leaf nodes (no children).
  - edge_label is required when the diagram shows branch labels (Yes/No); otherwise omit or set to "".
- Every node id must be unique across the tree.
- For all questions inside the "doubts" array, you MUST provide "x" and "y" integer coordinates representing where on the image the ambiguity exists.
- CRITICAL: The question text MUST be self-contained and descriptive. It should be understandable even without seeing the exact dot location. Reference surrounding text, shapes, or colors (e.g., "What does the blue oval below the 'Check Status' node represent?" instead of "What is this?").
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
            # Inject user-provided annotations into the prompt
            full_prompt = prompt

            img_w, img_h = 0, 0
            try:
                from PIL import Image
                with Image.open(image_path) as img:
                    img_w, img_h = img.size
            except Exception as e:
                self._logger.warning("Failed to get image dimensions for prompt: %s", e)

            if img_w > 0 and img_h > 0:
                full_prompt += (
                    f"\n\nCRITICAL COORDINATE RULE: When generating 'x' and 'y' coordinates for doubts, "
                    f"you MUST use a normalized 0-1000 coordinate system where (0,0) is the top-left corner "
                    f"and (1000, 1000) is the bottom-right corner. Do NOT use raw image pixels. "
                    f"For example, the exact center of the image is (500, 500)."
                )
                if annotations:
                    scaled_anns = []
                    for ann in annotations:
                        ann_copy = dict(ann)
                        if "x" in ann_copy and "y" in ann_copy:
                            ann_copy["x"] = int(ann_copy["x"] * 1000 / img_w)
                            ann_copy["y"] = int(ann_copy["y"] * 1000 / img_h)
                        scaled_anns.append(ann_copy)
                    full_prompt += _format_annotations(scaled_anns)
            else:
                if annotations:
                    full_prompt += _format_annotations(annotations)
            user_msg = {
                "role": "user",
                "content": [
                    {"type": "text", "text": full_prompt},
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

        # Map 0-1000 LLM output coordinates back to absolute hardware pixels
        if img_w > 0 and img_h > 0:
            if isinstance(data.get("doubts"), list):
                for doubt in data["doubts"]:
                    if isinstance(doubt, dict) and "x" in doubt and "y" in doubt:
                        try:
                            raw_x = float(doubt["x"])
                            raw_y = float(doubt["y"])
                            new_x = int(raw_x * img_w / 1000)
                            new_y = int(raw_y * img_h / 1000)
                            # Clamp within actual bounds to eliminate out-of-bounds rendering bugs
                            doubt["x"] = max(0, min(new_x, img_w))
                            doubt["y"] = max(0, min(new_y, img_h))
                        except (ValueError, TypeError):
                            pass

        include_raw = os.environ.get("LEMON_INCLUDE_RAW_ANALYSIS", "").lower() in {"1", "true", "yes"}
        if include_raw and isinstance(data, dict):
            data["_raw_model_output"] = raw
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


def _format_annotations(annotations: List[Dict[str, Any]]) -> str:
    """Format user annotations into a prompt section for the LLM."""
    if not annotations:
        return ""
    lines = [
        "\n\nThe user has provided the following annotations on the image to help clarify it."
        " Coordinates have been normalized to the 0-1000 system (origin top-left):"
    ]
    for i, ann in enumerate(annotations, 1):
        ann_type = ann.get("type", "unknown")
        if ann_type == "label":
            dot_x, dot_y = ann.get("x", 0), ann.get("y", 0)
            text = ann.get("text", "")
            lines.append(f'{i}. Label at ({dot_x}, {dot_y}): "{text}"')
        else:
            lines.append(f"{i}. Annotation: {ann}")
    lines.append(
        "Use these annotations to resolve ambiguities in the diagram. "
        "Give priority to user-provided labels over OCR when they conflict."
    )
    return "\n".join(lines)

