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
from ...utils.image import detect_image_media_type

logger = logging.getLogger(__name__)

# Prompt for the guidance extraction LLM call.
# Tells the model what to look for and the exact JSON schema to return.
_GUIDANCE_PROMPT = (
    "Extract all information from this flowchart image that sits OUTSIDE the main "
    "node-and-arrow flow. This includes:\n"
    "- Legends, keys, or colour explanations\n"
    "- Margin notes, sticky notes, handwritten annotations\n"
    "- Colour-coded detail boxes (e.g. green treatment panels, blue criteria boxes)\n"
    "- Footnoted or asterisked (*) panels that elaborate on a specific node\n"
    "- Any multi-step protocol, scoring algorithm, or assessment criteria described "
    "in a side panel\n\n"
    "Do NOT extract simple node labels or single-line arrow labels — only extract "
    "text blocks with substantive content (multiple sentences or bullet points).\n\n"
    "For each item you find, decide if it is a **subworkflow candidate**: a panel "
    "with enough multi-step logic (treatment escalation, scoring, assessment) to "
    "become its own standalone workflow. If yes, write a detailed brief describing "
    "what that subworkflow would compute — its inputs, step-by-step logic, and output.\n\n"
    "Also identify the ROOT NODE of the flowchart — the first real node after Start.\n"
    "- The root is the node with ONLY OUTGOING edges (no incoming edges from other flowchart nodes).\n"
    "- It may have a unique colour or shape, but not always.\n"
    "- Do NOT pick the node that seems most clinically/logically important. "
    "\"Primary\" does not always mean \"first\". Determine the root by STRUCTURE "
    "(arrow direction, which node has only outgoing edges), NOT by domain importance.\n"
    "- After identifying the root, list ALL of its outgoing edges and where they lead.\n\n"
    "Return a JSON object with two keys:\n"
    "```\n"
    "{\n"
    '  "root_node": {\n'
    '    "label": "exact label of the root node",\n'
    '    "type": "decision|process|calculation",\n'
    '    "outgoing_edges": ["description of each outgoing edge and where it leads"]\n'
    "  },\n"
    '  "guidance": [\n'
    "    {\n"
    '      "text": "exact text as written in the image",\n'
    '      "location": "where it appears (e.g. green box, right side)",\n'
    '      "category": "clarification|definition|constraint|note|legend|treatment_detail|criteria",\n'
    '      "linked_to": "exact label of the node this references, or null",\n'
    '      "link_type": "asterisk|footnote|arrow|color_group|proximity, or null",\n'
    '      "subworkflow_candidate": true/false,\n'
    '      "subworkflow_brief": "detailed description of subworkflow logic, or null"\n'
    "    }\n"
    "  ]\n"
    "}\n"
    "```\n"
    "Return JSON only, no other text."
)


class ExtractGuidanceTool(Tool):
    """Extract guidance/side-information from the uploaded workflow image.

    Makes a lightweight LLM call to identify notes, legends, annotations,
    and linked protocol panels that sit alongside the main flowchart.
    """

    name = "extract_guidance"
    description = (
        "Extract side information (sticky notes, legends, annotations, linked "
        "guidance panels) from an uploaded workflow image. Makes a separate "
        "API call and returns structured guidance items. Call this BEFORE "
        "building the workflow to discover extra context in the image. "
        "ONLY call this when the user has uploaded a new image. "
        "Do NOT call on text-only messages or edit requests. "
        "When multiple images are uploaded, pass the filename to select one."
    )
    parameters: List[ToolParameter] = [
        ToolParameter(
            name="filename",
            type="string",
            description="Name of the image file to extract guidance from. If omitted, uses the first image.",
            required=False,
        ),
    ]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        session_state = kwargs.get("session_state", {})
        uploaded_files = session_state.get("uploaded_files", [])
        requested_name = args.get("filename")

        # Collect all uploaded images
        images = [f for f in uploaded_files if f.get("file_type") == "image"]
        if not images:
            return {"success": False, "error": "No uploaded image found in session."}

        # If a filename is specified, find that specific image
        if requested_name:
            image_file = next(
                (f for f in images if f.get("name") == requested_name),
                None,
            )
            if not image_file:
                available = [f.get("name", "?") for f in images]
                return {
                    "success": False,
                    "error": f"Image '{requested_name}' not found. Available images: {available}",
                }
        else:
            image_file = images[0]

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

        media_type = detect_image_media_type(raw, image_path.suffix)

        logger.info("ExtractGuidanceTool calling LLM for %s (%d bytes)", image_path.name, len(raw))

        # Build messages with the image and guidance prompt
        messages = [
            {"role": "system", "content": "You extract side information from workflow images."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _GUIDANCE_PROMPT},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64,
                        },
                    },
                ],
            },
        ]

        try:
            resp = call_llm(
                messages,
                caller="extract_guidance",
                request_tag="extract_guidance",
            )
            raw_response = resp.text.strip()
        except Exception as exc:
            logger.warning("Guidance extraction LLM call failed: %s", exc)
            return {"success": False, "error": f"LLM call failed: {exc}"}

        # Parse JSON — strip code fences if present
        text = raw_response.strip()
        if text.startswith("```") and text.endswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()

        # Try parsing as object first (new format), fall back to array (legacy)
        root_node = None
        guidance_items: list = []

        start_obj = text.find("{")
        start_arr = text.find("[")

        try:
            if start_obj != -1 and (start_arr == -1 or start_obj < start_arr):
                # New format: {"root_node": {...}, "guidance": [...]}
                parsed = json.loads(text[start_obj:])
                if isinstance(parsed, dict):
                    root_node = parsed.get("root_node")
                    guidance_items = parsed.get("guidance", [])
            elif start_arr != -1:
                # Legacy format: bare JSON array
                guidance_items = json.loads(text[start_arr:])
            else:
                logger.debug("No JSON found in guidance response")
                return {"success": True, "guidance": []}
        except json.JSONDecodeError:
            logger.warning("Failed to parse guidance JSON")
            return {"success": True, "guidance": []}

        # Validate and normalize guidance items
        valid = []
        for item in guidance_items:
            if isinstance(item, dict) and "text" in item:
                item.setdefault("linked_to", None)
                item.setdefault("link_type", None)
                valid.append(item)

        logger.info("Extracted %d guidance items from %s", len(valid), image_path.name)

        result: Dict[str, Any] = {"success": True, "guidance": valid}
        if root_node and isinstance(root_node, dict):
            result["root_node"] = root_node
            logger.info("Root node identified: %s", root_node.get("label", "?"))
        return result
