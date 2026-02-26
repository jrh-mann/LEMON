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
from ..utils.image import image_to_data_url, file_to_data_url
from ..utils.analysis import normalize_analysis
from ..utils.cancellation import CancellationError


class Subagent:
    """Stateful subagent with persisted chat history."""

    # Prompt for extracting side information (sticky notes, annotations, legends)
    # from workflow images before the main analysis pass.
    _GUIDANCE_PROMPT = (
        "Examine this image for any written notes, annotations, or clarifications that "
        "exist OUTSIDE or ALONGSIDE the main flowchart structure. These might be:\n"
        "- Sticky notes or post-it notes\n"
        "- Margin annotations or handwritten text\n"
        "- Legends or keys explaining symbols\n"
        "- Clarification text or callout boxes\n"
        "- Definitions of terms or thresholds written near the diagram\n\n"
        "CRITICAL RULES:\n"
        "- ONLY report text that is LITERALLY VISIBLE in the image.\n"
        "- Do NOT infer, guess, or fabricate any information.\n"
        "- Do NOT extract text that is part of the flowchart nodes/arrows themselves.\n"
        "- If there are NO side notes or annotations, return an empty array: []\n"
        "- It is completely fine to return an empty array. Most images have no side notes.\n\n"
        'Return ONLY a JSON array. Each item:\n'
        '- "text": the EXACT text content as written in the image\n'
        '- "location": brief description of where it appears (e.g., "sticky note, top-right")\n'
        '- "category": one of "clarification", "definition", "constraint", "note", "legend"\n\n'
        "If nothing found, return: []\n"
        "Return JSON only, no extra text."
    )

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
        # guidance is populated for initial analysis only (not follow-ups)
        guidance: List[Dict[str, Any]] = []

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
            # Extract side information (sticky notes, legends, annotations) before main analysis
            guidance = self._extract_guidance(data_url=data_url, should_cancel=should_cancel)
            if guidance:
                self._logger.info(
                    "Extracted %d guidance items from image session_id=%s",
                    len(guidance), session_id,
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

            # Inject extracted guidance into the analysis prompt
            if guidance:
                lines = [
                    f'- [{g.get("category", "note")}] "{g.get("text", "")}" ({g.get("location", "")})'
                    for g in guidance
                ]
                full_prompt += (
                    "\n\n## Side Information Found in Image\n"
                    "The following notes and annotations were found alongside the flowchart. "
                    "Use them to inform your analysis:\n" + "\n".join(lines)
                )

            user_msg = {
                "role": "user",
                "content": [
                    {"type": "text", "text": full_prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        messages = [system_msg, *history_messages, user_msg]

        # Collect extended thinking from the LLM to use as reasoning context
        thinking_parts: List[str] = []

        def on_thinking(chunk: str) -> None:
            thinking_parts.append(chunk)

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
                thinking_budget=10000,
                on_thinking=on_thinking,
            ).strip()
        else:
            raw = call_llm(
                messages,
                max_completion_tokens=60000,
                response_format=None,
                caller="subagent",
                request_tag="analyze",
                should_cancel=should_cancel,
                thinking_budget=10000,
                on_thinking=on_thinking,
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
        # Attach the model's extended thinking as reasoning context
        data["reasoning"] = "".join(thinking_parts)
        # Attach extracted side information (guidance) from the image
        data["guidance"] = guidance

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


    def analyze_multi(
        self,
        *,
        classified_files: List[Dict[str, Any]],
        session_id: str,
        stream: Optional[Callable[[str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """Two-phase multi-file analysis: guidance collection, then tree analysis.

        Phase 1: Extract guidance from ALL guidance + mixed files.
        Phase 2: Single LLM call with ALL flowchart + mixed files + accumulated guidance.

        Each classified_file dict has: id, name, abs_path, file_type, purpose.
        """
        self._logger.info(
            "analyze_multi session_id=%s files=%d",
            session_id,
            len(classified_files),
        )

        def _progress(msg: str) -> None:
            """Emit progress status to the frontend."""
            if on_progress:
                on_progress(msg)

        def is_cancelled() -> bool:
            return bool(should_cancel and should_cancel())
        if is_cancelled():
            raise CancellationError("Subagent cancelled before multi-file analysis.")

        # --- Phase 1: Guidance collection ---
        # Run _extract_guidance on all guidance + mixed files
        guidance_files = [f for f in classified_files if f["purpose"] in ("guidance", "mixed")]
        all_guidance: List[Dict[str, Any]] = []
        for idx, gf in enumerate(guidance_files):
            if is_cancelled():
                raise CancellationError("Subagent cancelled during guidance extraction.")
            _progress(f"Extracting guidance ({idx + 1}/{len(guidance_files)})...")
            data_url = file_to_data_url(Path(gf["abs_path"]))
            items = self._extract_guidance(data_url=data_url, should_cancel=should_cancel)
            all_guidance.extend(items)
            self._logger.info(
                "Guidance from %s: %d items (total: %d)",
                gf["name"], len(items), len(all_guidance),
            )
        # All guidance extracted before any analysis begins

        # --- Phase 2: Tree analysis ---
        # Collect all flowchart + mixed files for a single LLM call
        analysis_files = [f for f in classified_files if f["purpose"] in ("flowchart", "mixed")]
        if not analysis_files:
            # No analysis files — return guidance only (use 'variables' for consistency)
            return {
                "variables": [],
                "outputs": [],
                "tree": {},
                "doubts": [],
                "reasoning": "",
                "guidance": all_guidance,
            }

        if is_cancelled():
            raise CancellationError("Subagent cancelled before analysis phase.")

        _progress(f"Analyzing {len(analysis_files)} file(s)...")

        # Build content blocks: one text block + one per file (image or PDF)
        content_blocks: List[Dict[str, Any]] = []

        # Build the analysis prompt — same as analyze() but with multi-file preamble
        multi_prompt = (
            "You are analyzing multiple files that together represent a SINGLE workflow. "
            "Combine all into ONE unified tree.\n\n"
        )
        multi_prompt += """Return ONLY a JSON object with this structure:
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
  "doubts": []
}

Rules:
- Use exact text from the diagrams.
- Every input must include an "id" computed as: input_{slug(name)}_{type}
- Input "name" should be canonical (short snake_case concept).
- Every DECISION node MUST include a structured "condition" object.
- For binary branches, set child edge_label to EXACTLY "true" or "false".
- This must be a single rooted tree starting at tree.start.
- Return JSON only, no extra text.
"""

        # Inject accumulated guidance into the prompt
        if all_guidance:
            lines = [
                f'- [{g.get("category", "note")}] "{g.get("text", "")}" ({g.get("location", "")})'
                for g in all_guidance
            ]
            multi_prompt += (
                "\n\n## Guidance Notes (extracted from accompanying files)\n"
                "The following notes, definitions, and annotations were found in the guidance files. "
                "Use them to inform your analysis of the workflow:\n" + "\n".join(lines)
            )

        content_blocks.append({"type": "text", "text": multi_prompt})

        # Add each analysis file as a content block
        for af in analysis_files:
            data_url = file_to_data_url(Path(af["abs_path"]))
            block = _build_content_block(data_url)
            content_blocks.append(block)

        messages = [
            {"role": "system", "content": "You extract structured data from workflow images and documents."},
            {"role": "user", "content": content_blocks},
        ]

        # Collect extended thinking
        thinking_parts: List[str] = []

        def on_thinking(chunk: str) -> None:
            thinking_parts.append(chunk)

        force_stream = os.environ.get("LEMON_SUBAGENT_STREAM", "").lower() in {"1", "true", "yes"}
        should_stream = stream is not None or force_stream

        if should_stream:
            def on_delta(chunk: str) -> None:
                if is_cancelled():
                    raise CancellationError("Subagent cancelled while streaming.")
                if stream:
                    stream(chunk)

            raw = call_llm_stream(
                messages,
                max_completion_tokens=60000,
                response_format=None,
                on_delta=on_delta,
                caller="subagent",
                request_tag="analyze_multi_stream",
                should_cancel=should_cancel,
                thinking_budget=10000,
                on_thinking=on_thinking,
            ).strip()
        else:
            raw = call_llm(
                messages,
                max_completion_tokens=60000,
                response_format=None,
                caller="subagent",
                request_tag="analyze_multi",
                should_cancel=should_cancel,
                thinking_budget=10000,
                on_thinking=on_thinking,
            ).strip()

        if is_cancelled():
            raise CancellationError("Subagent cancelled after multi-file LLM call.")
        if not raw:
            raise ValueError("LLM returned an empty response for multi-file analysis.")

        # Parse the JSON response
        system_msg = {"role": "system", "content": "You extract structured data from workflow images and documents."}
        user_msg = {"role": "user", "content": content_blocks}
        data = self._parse_json(raw, multi_prompt, [], system_msg, user_msg, should_cancel=should_cancel)
        data = normalize_analysis(data)
        data["reasoning"] = "".join(thinking_parts)
        data["guidance"] = all_guidance
        return data

    def _extract_guidance(
        self,
        *,
        data_url: str,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> List[Dict[str, Any]]:
        """Extract side information (sticky notes, legends, annotations) from a file.

        Performs a lightweight LLM call before the main analysis to identify any
        notes or annotations that exist alongside the flowchart. Supports both
        images (image_url content block) and PDFs (document content block).
        Returns a list of dicts with text/location/category, or [] on any failure (non-blocking).
        """
        try:
            # Build the appropriate content block based on media type
            file_block = _build_content_block(data_url)
            messages = [
                {"role": "system", "content": "You extract side information from workflow images and documents."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self._GUIDANCE_PROMPT},
                        file_block,
                    ],
                },
            ]
            raw = call_llm(
                messages,
                max_completion_tokens=4000,
                response_format=None,
                caller="subagent",
                request_tag="extract_guidance",
                should_cancel=should_cancel,
            ).strip()

            # Parse JSON array — strip code fences if present
            text = raw.strip()
            if text.startswith("```") and text.endswith("```"):
                text = text.strip("`").strip()
                if text.lower().startswith("json"):
                    text = text[4:].strip()

            # Find the first '[' to locate the JSON array
            start = text.find("[")
            if start == -1:
                self._logger.debug("No JSON array found in guidance response")
                return []

            parsed = json.loads(text[start:])
            if not isinstance(parsed, list):
                self._logger.debug("Guidance response was not a list")
                return []

            # Validate each item has required keys
            valid = []
            for item in parsed:
                if isinstance(item, dict) and "text" in item:
                    valid.append(item)
            return valid

        except Exception as exc:
            # Non-blocking — guidance extraction failure should never break analysis
            self._logger.warning("Guidance extraction failed (non-blocking): %s", exc)
            return []

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


def _build_content_block(data_url: str) -> Dict[str, Any]:
    """Build an LLM content block from a data URL — image_url for images, document for PDFs."""
    if data_url.startswith("data:application/pdf"):
        # Extract base64 data for Anthropic document content block
        _, b64 = data_url.split(";base64,", 1)
        return {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": b64,
            },
        }
    # Default: image content block
    return {"type": "image_url", "image_url": {"url": data_url}}


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

