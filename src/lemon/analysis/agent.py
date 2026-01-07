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

    def analyze(self, image: Path) -> WorkflowAnalysis:
        """Run workflow analysis and parse into typed model."""
        from src.utils.request_utils import (  # late import (legacy module)
            image_to_base64,
            make_request,
        )

        img_base64, media_type = self._load_image(image)
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": img_base64},
                    },
                    {"type": "text", "text": self.analysis_prompt},
                ],
            }
        ]

        response = make_request(
            messages=messages, max_tokens=self.max_tokens, system=self.system_prompt
        )
        response_text = response.content[0].text if response.content else ""

        data = self._parse_json_best_effort(response_text)
        try:
            return WorkflowAnalysis.model_validate(data)
        except Exception as e:
            raise WorkflowAnalysisError(
                "Failed to validate workflow analysis JSON against schema",
                context={"error": str(e)},
            ) from e

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
        """Extract all unique output strings."""
        outputs: set[str] = set()
        for out in analysis.outputs:
            if out.name:
                outputs.add(out.name)
        for path in analysis.workflow_paths:
            if path.output:
                outputs.add(path.output)
        for dp in analysis.decision_points:
            for branch in dp.branches:
                if branch.outcome and not branch.outcome.startswith(("leads to", "next")):
                    outputs.add(branch.outcome)
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

        # Second attempt: extract JSON object from surrounding text.
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                data2 = json.loads(match.group(0))
                if isinstance(data2, dict):
                    return data2
                raise WorkflowAnalysisError(
                    "Extracted JSON was not an object",
                    context={"preview": match.group(0)[:200]},
                )
            except json.JSONDecodeError:
                pass

        raise WorkflowAnalysisError(
            "Failed to parse JSON from analysis response", context={"preview": text[:500]}
        )

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
            return StandardizedRange(min=min_val, max=max_val)

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
            return StandardizedRange(min=min(nums), max=max(nums))
        return StandardizedRange(value=nums[0])
