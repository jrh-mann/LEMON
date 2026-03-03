"""Tool that makes a separate LLM call to extract guidance from an uploaded image.

Extracts side information — sticky notes, legends, annotations, linked protocol
panels, colour-coded detail boxes — that exist alongside the main flowchart.
Returns structured JSON so the orchestrator knows about extra context before
building the workflow.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from ..core import Tool, ToolParameter
from ...llm import call_llm

logger = logging.getLogger(__name__)

# Prompt copied from the original subagent guidance extractor.
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


class ExtractGuidanceTool(Tool):
    """Extract guidance/side-information from the uploaded workflow image.

    Makes a lightweight LLM call to identify notes, legends, annotations,
    and linked protocol panels that sit alongside the main flowchart.
    """

    name = "extract_guidance"
    description = (
        "Extract side information (sticky notes, legends, annotations, linked "
        "guidance panels) from the uploaded workflow image. Returns a structured "
        "list of guidance items so you know about extra context before building."
    )
    parameters: List[ToolParameter] = []  # No params — uses session_state uploaded_files

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        uploaded_files = session_state.get("uploaded_files", [])

        # Find first image in uploaded files
        image_file = next(
            (f for f in uploaded_files if f.get("file_type") == "image"),
            None,
        )
        if not image_file:
            return {"success": False, "error": "No uploaded image found in session."}

        image_path = Path(image_file["path"])
        if not image_path.is_absolute():
            repo_root = session_state.get("repo_root")
            if repo_root:
                image_path = Path(repo_root) / image_path

        if not image_path.exists():
            return {"success": False, "error": f"Image file not found: {image_path}"}

        # Read and encode the image
        raw = image_path.read_bytes()
        b64 = base64.b64encode(raw).decode()

        suffix = image_path.suffix.lower()
        media_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
        media_type = media_map.get(suffix, f"image/{suffix.lstrip('.')}")

        logger.info("ExtractGuidanceTool calling LLM for %s (%d bytes)", image_path.name, len(raw))

        # Build messages with the image and guidance prompt
        messages = [
            {"role": "system", "content": "You extract side information from workflow images."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _GUIDANCE_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{b64}"},
                    },
                ],
            },
        ]

        try:
            raw_response = call_llm(
                messages,
                max_completion_tokens=5000,
                caller="extract_guidance",
                request_tag="extract_guidance",
            ).strip()
        except Exception as exc:
            logger.warning("Guidance extraction LLM call failed: %s", exc)
            return {"success": False, "error": f"LLM call failed: {exc}"}

        # Parse JSON array — strip code fences if present
        text = raw_response.strip()
        if text.startswith("```") and text.endswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()

        start = text.find("[")
        if start == -1:
            logger.debug("No JSON array found in guidance response")
            return {"success": True, "guidance": []}

        try:
            parsed = json.loads(text[start:])
        except json.JSONDecodeError:
            logger.warning("Failed to parse guidance JSON")
            return {"success": True, "guidance": []}

        # Validate and normalize items
        valid = []
        for item in parsed:
            if isinstance(item, dict) and "text" in item:
                item.setdefault("linked_to", None)
                item.setdefault("link_type", None)
                valid.append(item)

        logger.info("Extracted %d guidance items from %s", len(valid), image_path.name)
        return {"success": True, "guidance": valid}
