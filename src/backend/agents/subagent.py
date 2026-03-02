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
from ..validation.tree_validator import TreeValidator
from ..validation.retry_harness import validate_and_retry


class Subagent:
    """Stateful subagent with persisted chat history."""

    # Prompt for extracting side information (sticky notes, annotations, legends)
    # from workflow images before the main analysis pass.
    # Prompt for extracting both standalone side information AND detailed guidance
    # panels that are linked to specific flowchart nodes (e.g., treatment protocol
    # boxes, asterisk-referenced panels, color-coded detail panels).
    _GUIDANCE_PROMPT = (
        "Examine this image for guidance information. There are TWO types:\n\n"
        "## Type 1: Standalone Side Notes\n"
        "Notes, annotations, or clarifications that exist OUTSIDE the main flowchart:\n"
        "- Sticky notes or post-it notes\n"
        "- Margin annotations or handwritten text\n"
        "- Legends or keys explaining symbols\n"
        "- Definitions of terms or thresholds written near the diagram\n\n"
        "## Type 2: Referenced Guidance Panels\n"
        "Detailed guidance panels that are LINKED to specific flowchart nodes via:\n"
        "- Asterisk (*) or footnote references (e.g., a node says 'Treatment*' and a "
        "panel elsewhere describes the treatment steps)\n"
        "- Arrows or lines connecting a panel to a node\n"
        "- Color-coded boxes that elaborate on a node (e.g., green boxes with treatment "
        "protocols, blue boxes with assessment criteria)\n"
        "- Proximity — a detailed panel positioned next to a node it describes\n\n"
        "CRITICAL RULES:\n"
        "- ONLY report text that is LITERALLY VISIBLE in the image.\n"
        "- Do NOT infer, guess, or fabricate any information.\n"
        "- Do NOT extract simple node labels or short arrow labels.\n"
        "- DO extract detailed guidance panels even if they look like part of the diagram, "
        "as long as they contain multi-sentence or multi-step information.\n"
        "- If there are NO guidance items, return an empty array: []\n"
        "- It is completely fine to return an empty array.\n\n"
        'Return ONLY a JSON array. Each item:\n'
        '- "text": the EXACT text content as written in the image\n'
        '- "location": brief description of where it appears (e.g., "green box, right side")\n'
        '- "category": one of "clarification", "definition", "constraint", "note", '
        '"legend", "treatment_detail", "criteria"\n'
        '- "linked_to": the exact text of the flowchart node this guidance references, '
        "or null if standalone\n"
        '- "link_type": one of "asterisk", "footnote", "arrow", "color_group", '
        '"proximity", or null if standalone\n\n'
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
        on_thinking: Optional[Callable[[str], None]] = None,
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
- PREFER numeric/float variables with threshold comparators over pre-baked booleans.
  When a diagram says "Is A1c > 58?" or "A1c controlled?", model the variable as
  {"id": "input_a1c_float", "name": "a1c", "type": "float"} and the decision condition as
  {"input_id": "input_a1c_float", "comparator": "gt", "value": 58}.
  Do NOT create a boolean like "a1c_controlled: bool" — use the raw measurable value.
  Only use type "bool" for genuinely binary clinical facts (e.g., "metformin_tolerated",
  "admission_required") that have no underlying numeric threshold.
- If a decision/action depends on one or more inputs, include "input_ids" on that node
  referencing the input ids.
- Every DECISION node MUST include a structured "condition" object.
  Simple condition: {"input_id": "...", "comparator": "...", "value": ..., "value2": ... optional}
  Compound condition (AND/OR): {"operator": "and"|"or", "conditions": [simple, simple, ...]}
  - Use compound when a decision checks MULTIPLE variables (e.g., "Symptoms present AND A1c > 58").
  - Compound conditions must have >= 2 sub-conditions. No nesting allowed.
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
  - Every leaf node (no children) MUST have type "output". If a terminal step looks
    like an action (e.g., "Continue metformin"), it is still an output because it is
    the final recommendation of that branch.
  - edge_label is required when the diagram shows branch labels (Yes/No); otherwise omit or set to "".
- Output node labels MUST be specific and distinguishable. Use the exact treatment/outcome
  text from the diagram. Do NOT generalize to vague labels like "Continue current treatment" —
  each output should have a unique, clinically actionable label.
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
        # Image dimensions for coordinate mapping (set during initial analysis)
        img_w, img_h = 0, 0

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
                full_prompt += _format_guidance(
                    guidance, header="Side Information Found in Image"
                )

            user_msg = {
                "role": "user",
                "content": [
                    {"type": "text", "text": full_prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        messages = [system_msg, *history_messages, user_msg]

        # Collect extended thinking from the LLM to use as reasoning context.
        # Forward each chunk to the caller for real-time streaming if a callback is provided.
        thinking_parts: List[str] = []

        def _on_thinking_chunk(chunk: str) -> None:
            thinking_parts.append(chunk)
            if on_thinking:
                on_thinking(chunk)

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
                on_thinking=_on_thinking_chunk,
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
                on_thinking=_on_thinking_chunk,
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

        # Structural validation of the nested tree — retry via LLM if invalid.
        data, remaining_errors = self._validate_tree_with_retry(
            data,
            system_msg=system_msg,
            history_messages=history_messages,
            user_msg=user_msg,
            assistant_raw=raw,
            should_cancel=should_cancel,
        )
        # Surface remaining structural errors as doubts so the user sees them.
        if remaining_errors:
            self._attach_validation_doubts(data, remaining_errors)

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
        relationship: Optional[str] = None,
        on_thinking: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """Two-phase multi-file analysis: guidance collection, then tree analysis.

        Phase 1: Extract guidance from ALL guidance + mixed files.
        Phase 2: Single LLM call with ALL flowchart + mixed files + accumulated guidance.
        The optional ``relationship`` string provides user context about how the files
        relate to each other and what information to extract from each.

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
            "You are analyzing multiple files that together form a COMBINED workflow. "
            "Each file contains part of the overall patient/process pathway.\n\n"
            "## CRITICAL: Merging Rules\n"
            "- EVERY file's logic MUST appear in the final tree. Do NOT omit any file.\n"
            "- Look for natural connection points between the workflows:\n"
            "  - A test result or condition in one workflow that triggers the other\n"
            "  - Shared patient populations or overlapping conditions\n"
            "  - Sequential steps where one pathway leads into another\n"
            "- If workflows share a common entry point, merge them there.\n"
            "- If one workflow naturally feeds into another (e.g., a diagnostic workup "
            "discovers a condition that triggers a treatment pathway), chain them at "
            "that decision point.\n"
            "- If no obvious link exists, create a common start node that branches "
            "into each pathway via a decision node.\n"
            "- The result must be ONE tree preserving ALL logic from ALL files.\n\n"
        )
        # Inject user-provided relationship context so the LLM understands how
        # the files connect and what to extract from each.
        if relationship:
            multi_prompt += (
                "## User Context\n"
                "The user described how these files relate and what to extract:\n"
                f"{relationship}\n\n"
                "Use this context to guide how you merge the workflows. "
                "Pay special attention to the user's description of connection points "
                "and what information matters from each file.\n\n"
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
            multi_prompt += _format_guidance(
                all_guidance,
                header="Guidance Notes (extracted from accompanying files)",
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

        # Collect extended thinking and forward chunks to caller for real-time streaming
        thinking_parts: List[str] = []

        def _on_thinking_chunk(chunk: str) -> None:
            thinking_parts.append(chunk)
            if on_thinking:
                on_thinking(chunk)

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
                on_thinking=_on_thinking_chunk,
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
                on_thinking=_on_thinking_chunk,
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

        # Structural validation of the nested tree — retry via LLM if invalid.
        data, remaining_errors = self._validate_tree_with_retry(
            data,
            system_msg=system_msg,
            history_messages=[],
            user_msg=user_msg,
            assistant_raw=raw,
            should_cancel=should_cancel,
        )
        if remaining_errors:
            self._attach_validation_doubts(data, remaining_errors)

        data["reasoning"] = "".join(thinking_parts)
        data["guidance"] = all_guidance

        # Persist to history so publish_latest_analysis can load it later
        self.history.add_message(session_id, "user", multi_prompt)
        self.history.add_message(session_id, "assistant", json.dumps(data))
        self.history.store_analysis(session_id, data)

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
                max_completion_tokens=5000,
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

            parsed = _parse_json_array(text[start:])
            if parsed is None:
                self._logger.warning("Failed to parse guidance JSON array")
                return []

            # Validate each item has required keys and normalize optional fields
            valid = []
            for item in parsed:
                if isinstance(item, dict) and "text" in item:
                    # Ensure linked guidance fields always present
                    if "linked_to" not in item:
                        item["linked_to"] = None
                    if "link_type" not in item:
                        item["link_type"] = None
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

    # ------------------------------------------------------------------
    # Tree structural validation helpers
    # ------------------------------------------------------------------

    _tree_validator = TreeValidator()

    def _validate_tree_with_retry(
        self,
        data: Dict[str, Any],
        *,
        system_msg: dict,
        history_messages: list,
        user_msg: dict,
        assistant_raw: str,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> tuple:
        """Run TreeValidator on *data*, retrying via the LLM if invalid.

        Returns ``(data, remaining_errors)`` — remaining_errors is empty
        when validation passes (possibly after retries).
        """

        def _retry_llm(error_text: str) -> str:
            """Re-call the LLM with the original conversation + error feedback."""
            if should_cancel and should_cancel():
                raise CancellationError("Subagent cancelled before structural retry.")
            retry_messages = [
                system_msg,
                *history_messages,
                user_msg,
                {"role": "assistant", "content": assistant_raw},
                {
                    "role": "user",
                    "content": (
                        "Your previous JSON response had structural errors in the "
                        "tree. Each error below includes a FIX hint explaining "
                        "what is expected.\n\n"
                        f"{error_text}\n\n"
                        "Return the COMPLETE corrected JSON with these issues "
                        "fixed. Keep everything else unchanged. Return ONLY "
                        "valid JSON, no extra text."
                    ),
                },
            ]
            return call_llm(
                retry_messages,
                max_completion_tokens=60000,
                response_format=None,
                caller="subagent",
                request_tag="tree_structure_retry",
                should_cancel=should_cancel,
            ).strip()

        def _parse_and_normalize(raw: str) -> Dict[str, Any]:
            """Parse raw LLM output and normalize it."""
            cleaned = raw.strip()
            if cleaned.startswith("```") and cleaned.endswith("```"):
                cleaned = cleaned.strip("`").strip()
                if cleaned.lower().startswith("json"):
                    cleaned = cleaned[4:].strip()
            parsed = json.loads(cleaned)
            if not isinstance(parsed, dict):
                raise ValueError("Expected a JSON object.")
            return normalize_analysis(parsed)

        return validate_and_retry(
            data=data,
            validate_fn=self._tree_validator.validate,
            format_errors_fn=TreeValidator.format_errors,
            retry_llm_fn=_retry_llm,
            parse_fn=_parse_and_normalize,
            max_retries=2,
            logger=self._logger,
        )

    @staticmethod
    def _attach_validation_doubts(
        data: Dict[str, Any],
        errors: list,
    ) -> None:
        """Append remaining validation errors as doubts so the user sees them."""
        doubts = data.get("doubts")
        if not isinstance(doubts, list):
            doubts = []
            data["doubts"] = doubts
        for err in errors:
            doubts.append({
                "text": f"[{err.code}] {err.message}",
                "source": "tree_validator",
            })


def _parse_json_array(text: str) -> Optional[List[Dict[str, Any]]]:
    """Robustly parse a JSON array from potentially malformed LLM output.

    Tries in order:
    1. Strict json.loads
    2. raw_decode (ignores trailing text)
    3. Strip trailing commas before ] and retry
    Returns None if all attempts fail.
    """
    import re as _re

    # Attempt 1: strict parse
    try:
        result = json.loads(text)
        return result if isinstance(result, list) else None
    except json.JSONDecodeError:
        pass

    # Attempt 2: raw_decode — handles trailing text after the array
    try:
        decoder = json.JSONDecoder()
        result, _ = decoder.raw_decode(text)
        return result if isinstance(result, list) else None
    except json.JSONDecodeError:
        pass

    # Attempt 3: fix trailing commas (e.g. `{...}, ]`) and retry
    cleaned = _re.sub(r",\s*([}\]])", r"\1", text)
    try:
        result = json.loads(cleaned)
        return result if isinstance(result, list) else None
    except json.JSONDecodeError:
        pass

    # Attempt 4: find matching ] bracket, extract substring, retry with cleaning
    depth = 0
    end_idx = -1
    for i, ch in enumerate(text):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end_idx = i
                break
    if end_idx > 0:
        subset = text[: end_idx + 1]
        subset = _re.sub(r",\s*([}\]])", r"\1", subset)
        try:
            result = json.loads(subset)
            return result if isinstance(result, list) else None
        except json.JSONDecodeError:
            pass

    return None


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


def _format_guidance(guidance: List[Dict[str, Any]], *, header: str) -> str:
    """Format guidance items into a prompt section, splitting standalone vs linked.

    Standalone items (linked_to is None) are shown as simple category/text/location
    lines. Linked items include a reference to the flowchart node they describe.

    Args:
        guidance: List of guidance dicts with text, location, category, linked_to, link_type.
        header: Section header text (e.g., "Side Information Found in Image").
    """
    if not guidance:
        return ""

    standalone = [g for g in guidance if not g.get("linked_to")]
    linked = [g for g in guidance if g.get("linked_to")]

    parts: list[str] = [f"\n\n## {header}\n"]

    if standalone:
        parts.append("The following notes and annotations provide context:\n")
        for g in standalone:
            parts.append(
                f'- [{g.get("category", "note")}] "{g.get("text", "")}" '
                f'({g.get("location", "")})'
            )

    if linked:
        parts.append(
            "\nThe following detailed guidance panels are linked to specific "
            "flowchart nodes:\n"
        )
        for g in linked:
            link_via = f" via {g['link_type']}" if g.get("link_type") else ""
            parts.append(
                f'- [{g.get("category", "note")}] "{g.get("text", "")}" '
                f'({g.get("location", "")}) -> linked to node: '
                f'"{g["linked_to"]}"{link_via}'
            )

    return "\n".join(parts)


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

