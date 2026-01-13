"""Workflow analysis agent for reading and analyzing workflow diagrams."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from ..core.exceptions import WorkflowAnalysisError
from ..core.workflow import StandardizedInput, StandardizedRange, WorkflowAnalysis
from ..utils.logging import get_logger

logger = get_logger(__name__)


def _load_prompts() -> Tuple[str, str, int]:
    """Load analysis prompts from repo-level config (fallback to defaults)."""
    try:
        # Keep compatibility with existing repo layout.
        from workflow_prompts import MAX_TOKENS, SINGLE_ANALYSIS_PROMPT
        from workflow_prompts import SYSTEM_PROMPT as WORKFLOW_ANALYSIS_SYSTEM_PROMPT

        return WORKFLOW_ANALYSIS_SYSTEM_PROMPT, SINGLE_ANALYSIS_PROMPT, MAX_TOKENS
    except Exception:
        return (
            "You are an expert workflow analysis assistant.",
            "Analyze this workflow and output JSON.",
            4096,
        )


class WorkflowAnalyzer:
    """Analyze a workflow image into structured workflow analysis."""

    def __init__(self, *, system_prompt: Optional[str] = None, max_tokens: Optional[int] = None):
        default_system, default_prompt, default_max = _load_prompts()
        self.system_prompt = system_prompt or default_system
        self.analysis_prompt = default_prompt
        self.max_tokens = max_tokens if max_tokens is not None else default_max

    def analyze(
        self, image: Path, stream_callback: Optional[Any] = None
    ) -> WorkflowAnalysis:
        """Run workflow analysis and parse into typed model.
        
        Args:
            image: Path to workflow image
            stream_callback: Optional callable(str) to call with each text chunk as it streams
        """
        from src.utils.request_utils import (  # late import (legacy module)
            image_to_base64,
            make_request,
            make_request_stream,
        )

        img_base64, media_type = self._load_image(image)

        def build_messages(prompt_text: str) -> List[Dict[str, Any]]:
            return [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": img_base64,
                            },
                        },
                        {"type": "text", "text": prompt_text},
                    ],
                }
            ]

        def run_request(prompt_text: str, *, stream: bool) -> str:
            messages = build_messages(prompt_text)
            if stream and stream_callback:
                response_text = ""
                for chunk in make_request_stream(
                    messages=messages, max_tokens=self.max_tokens, system=self.system_prompt
                ):
                    response_text += chunk
                    stream_callback(chunk)
                return response_text
            response = make_request(
                messages=messages, max_tokens=self.max_tokens, system=self.system_prompt
            )
            return response.content[0].text if response.content else ""

        def parse_and_validate(response_text: str) -> WorkflowAnalysis:
            data = self._parse_json_best_effort(response_text)
            data = self._normalize_analysis_payload(data)
            return WorkflowAnalysis.model_validate(data)

        response_text = run_request(self.analysis_prompt, stream=bool(stream_callback))
        try:
            return parse_and_validate(response_text)
        except Exception as first_error:
            error_summary = str(first_error)[:2000]
            retry_prompt = (
                "Your previous JSON failed schema validation. Fix the JSON to match the schema "
                "exactly. Every workflow_paths item MUST have a non-empty output string. "
                "If an output is unknown, remove that workflow_paths entry. Do NOT use null. "
                "If a field is a date, keep min/max as ISO date strings and set type to 'date'. "
                "Return JSON only.\n\nVALIDATION_ERRORS:\n"
                + error_summary
                + "\n\nPREVIOUS_RESPONSE:\n"
                + response_text[:8000]
            )
            retry_text = run_request(retry_prompt, stream=False)
            try:
                return parse_and_validate(retry_text)
            except Exception as second_error:
                raise WorkflowAnalysisError(
                    "Failed to validate workflow analysis JSON against schema",
                    context={"error": str(second_error), "previous_error": str(first_error)},
                ) from second_error

    def extract_standardized_inputs(self, analysis: WorkflowAnalysis) -> List[StandardizedInput]:
        """Convert raw analysis inputs into the normalized `workflow_inputs.json` schema."""
        standardized: List[StandardizedInput] = []
        for inp in analysis.inputs:
            standardized.append(
                StandardizedInput(
                    input_name=inp.name,
                    input_type=self._normalize_type(inp.type, inp.format),  # type: ignore[arg-type]
                    range=self._extract_range(inp.possible_values, inp.constraints),
                    description=inp.description,
                )
            )
        return standardized

    def extract_outputs(self, analysis: WorkflowAnalysis) -> List[str]:
        """Extract all unique *terminal* output strings.

        Important: We intentionally do NOT treat decision branch `outcome` text as an output.
        Models often use that field for intermediate actions / transitions (e.g. "Proceed to…"),
        which pollutes `workflow_outputs.json` with non-terminal steps and near-duplicates.
        """
        outputs: set[str] = set()
        for out in analysis.outputs:
            if out.name:
                outputs.add(out.name)
        for path in analysis.workflow_paths:
            if path.output:
                outputs.add(path.output)
        return sorted(outputs)

    def _load_image(self, image_path: Path) -> Tuple[str, str]:
        img = Image.open(image_path)
        format_map = {
            "JPEG": ("image/jpeg", "JPEG"),
            "JPG": ("image/jpeg", "JPEG"),
            "PNG": ("image/png", "PNG"),
            "WEBP": ("image/webp", "WEBP"),
            "GIF": ("image/gif", "GIF"),
        }
        img_format = (img.format or "PNG").upper()
        media_type, format_str = format_map.get(img_format, ("image/png", "PNG"))

        from src.utils.request_utils import image_to_base64  # late import (legacy module)

        return image_to_base64(img, format=format_str), media_type

    def _parse_json_best_effort(self, text: str) -> Dict[str, Any]:
        # First attempt: plain JSON.
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
            raise WorkflowAnalysisError(
                "Analysis response JSON was not an object", context={"preview": text[:200]}
            )
        except json.JSONDecodeError:
            pass

        def extract_json_objects(raw: str) -> List[str]:
            objects: List[str] = []
            depth = 0
            start: Optional[int] = None
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
                if ch == "{":
                    if depth == 0:
                        start = idx
                    depth += 1
                elif ch == "}" and depth > 0:
                    depth -= 1
                    if depth == 0 and start is not None:
                        objects.append(raw[start : idx + 1])
                        start = None
            return objects

        # Second attempt: extract balanced JSON objects from surrounding text.
        for candidate in extract_json_objects(text):
            try:
                data2 = json.loads(candidate)
                if isinstance(data2, dict):
                    return data2
                raise WorkflowAnalysisError(
                    "Extracted JSON was not an object",
                    context={"preview": candidate[:200]},
                )
            except json.JSONDecodeError:
                continue

        raise WorkflowAnalysisError(
            "Failed to parse JSON from analysis response", context={"preview": text[:500]}
        )

    def _normalize_analysis_payload(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(data, dict):
            return data

        analysis_meta = data.get("analysis_meta")
        if not isinstance(analysis_meta, dict):
            analysis_meta = {}
        for key in ("ambiguities", "questions", "warnings"):
            value = analysis_meta.get(key)
            if value is None:
                analysis_meta[key] = []
                continue
            if isinstance(value, list):
                cleaned = [str(item).strip() for item in value if str(item).strip()]
                analysis_meta[key] = cleaned
                continue
            text = str(value).strip()
            analysis_meta[key] = [text] if text else []
        data["analysis_meta"] = analysis_meta

        inputs = data.get("inputs")
        if isinstance(inputs, list):
            for inp in inputs:
                if not isinstance(inp, dict):
                    continue
                possible_values = inp.get("possible_values")
                if not isinstance(possible_values, dict):
                    continue
                if str(possible_values.get("type", "")).lower() != "range":
                    continue

                for key in ("min", "max"):
                    raw = possible_values.get(key)
                    if isinstance(raw, (int, float)) or raw is None:
                        continue
                    if isinstance(raw, str):
                        try:
                            possible_values[key] = float(raw)
                        except ValueError:
                            # Keep non-numeric strings (e.g., ISO dates).
                            possible_values[key] = raw

        workflow_paths = data.get("workflow_paths")
        if isinstance(workflow_paths, list):
            normalized_paths = []
            for idx, path in enumerate(workflow_paths, 1):
                if not isinstance(path, dict):
                    continue
                output = path.get("output")
                if output is None or (isinstance(output, str) and not output.strip()):
                    continue
                if not path.get("path_id"):
                    path["path_id"] = f"path_{idx}"
                normalized_paths.append(path)
            data["workflow_paths"] = normalized_paths

        return data

    def _normalize_type(self, type_str: str, format_str: str) -> str:
        type_lower = (type_str or "").lower()
        format_lower = (format_str or "").lower()

        if "int" in format_lower or "integer" in format_lower:
            return "Int"
        if "float" in format_lower or "decimal" in format_lower:
            return "Float"
        if "bool" in format_lower or "boolean" in format_lower:
            return "bool"
        if "date" in format_lower:
            return "date"

        if "numeric" in type_lower or "number" in type_lower:
            return "Float"
        if "text" in type_lower or "string" in type_lower:
            return "str"
        if "bool" in type_lower or "boolean" in type_lower:
            return "bool"
        if "categorical" in type_lower or "enum" in type_lower:
            return "str"
        if "date" in type_lower:
            return "date"
        return "str"

    def _extract_range(self, possible_values: Any, constraints: str) -> Any:
        # Note: this mirrors the repo's current JSON artifact format for compatibility.
        if possible_values is None:
            return self._range_from_constraints(constraints)

        pv_type = getattr(possible_values, "type", None)
        if pv_type == "range":
            min_val = getattr(possible_values, "min", None)
            max_val = getattr(possible_values, "max", None)
            # Return dict instead of StandardizedRange to avoid "value": null in JSON
            result = {}
            if min_val is not None:
                result["min"] = min_val
            if max_val is not None:
                result["max"] = max_val
            return result if result else None

        if pv_type == "enum":
            values = getattr(possible_values, "values", []) or []
            return list(values)

        if pv_type == "unbounded":
            return None

        return self._range_from_constraints(constraints)

    def _range_from_constraints(self, constraints: str) -> Any:
        if not constraints:
            return None
        numbers = re.findall(r"\d+\.?\d*", constraints)
        if not numbers:
            return None
        nums = [float(n) for n in numbers]
        if len(nums) >= 2:
            return {"min": min(nums), "max": max(nums)}
        return {"value": nums[0]}
