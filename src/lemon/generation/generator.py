"""Deterministic Python code generation from workflow analysis."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image

from ..core.workflow import WorkflowAnalysis
from ..utils.logging import get_logger
from .formatter import normalize_js_literals


@dataclass(frozen=True)
class GenerationContext:
    """Generation-time feedback and additional context."""

    failures: Optional[List[Dict[str, Any]]] = None
    test_cases_file: Optional[Path] = None


class CodeGenerator:
    """Generates deterministic Python code from workflow analysis."""

    def __init__(self, *, max_tokens: int = 64000):
        self.max_tokens = max_tokens
        self.logger = get_logger(__name__)

    def generate(
        self,
        *,
        workflow_image_path: Path,
        workflow_data: WorkflowAnalysis,
        valid_outputs: List[str],
        context: Optional[GenerationContext] = None,
    ) -> str:
        """Generate Python code implementing the workflow logic."""
        from src.utils.request_utils import image_to_base64, make_request  # legacy module

        ctx = context or GenerationContext()

        img = Image.open(workflow_image_path)
        img_format = (img.format or "PNG").upper()
        format_map = {
            "JPEG": ("PNG", "image/png"),
            "JPG": ("PNG", "image/png"),
            "PNG": ("PNG", "image/png"),
            "WEBP": ("PNG", "image/png"),
            "GIF": ("PNG", "image/png"),
        }
        format_str, media_type = format_map.get(img_format, ("PNG", "image/png"))
        img_base64 = image_to_base64(img, format=format_str)

        context_text = self._build_context(
            workflow_data=workflow_data,
            valid_outputs=valid_outputs,
            failures=ctx.failures,
            test_cases_file=ctx.test_cases_file,
        )

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": img_base64},
                    },
                    {
                        "type": "text",
                        "text": CODE_GENERATION_PROMPT + "\n\nCONTEXT:\n" + context_text,
                    },
                ],
            }
        ]

        response = make_request(
            messages,
            max_tokens=self.max_tokens,
            system=PYTHON_ONLY_SYSTEM_PROMPT,
        )
        code: str = response.content[0].text if response.content else ""

        # Clean up markdown code blocks if present.
        code = code.replace("```python", "").replace("```", "").strip()

        # Normalize common JS drift.
        code = normalize_js_literals(code)
        return code

    def _build_context(
        self,
        *,
        workflow_data: WorkflowAnalysis,
        valid_outputs: List[str],
        failures: Optional[List[Dict[str, Any]]],
        test_cases_file: Optional[Path],
    ) -> str:
        parts: List[str] = []

        parts.append("=" * 80)
        parts.append("COMPLETE WORKFLOW ANALYSIS")
        parts.append("=" * 80)
        parts.append(workflow_data.model_dump_json(indent=2))

        if test_cases_file:
            try:
                with open(test_cases_file) as f:
                    test_cases = json.load(f)
                if test_cases:
                    input_names: set[str] = set()
                    for tc in test_cases[:10]:
                        for key in tc.keys():
                            if key != "expected_output":
                                input_names.add(key)
                    if input_names:
                        parts.append("\n" + "=" * 80)
                        parts.append("ACTUAL INPUT NAMES FROM TEST CASES")
                        parts.append("=" * 80)
                        parts.append("Use these EXACT input names in your code:")
                        parts.append(json.dumps(sorted(list(input_names)), indent=2))
            except Exception:
                pass

        parts.append("\n" + "=" * 80)
        parts.append("VALID OUTPUTS (MUST MATCH EXACTLY)")
        parts.append("=" * 80)
        parts.append(json.dumps(valid_outputs, indent=2))

        if failures:
            failure_report = analyze_failure_patterns(failures)
            parts.append("\n" + "=" * 80)
            parts.append("CRITICAL FEEDBACK - FIX THESE ISSUES")
            parts.append("=" * 80)
            parts.append(failure_report)
            parts.append("\nINSTRUCTIONS:")
            parts.append("- Analyze why these specific inputs caused these errors")
            parts.append("- Check if you're using the correct input names")
            parts.append("- Verify your conditions match the workflow decision points")
            parts.append("- Ensure output strings match the VALID OUTPUTS exactly")
            parts.append("- Trace through the workflow_paths to understand the correct flow")

        return "\n".join(parts)


def analyze_failure_patterns(failures: List[Dict[str, Any]]) -> str:
    """Group failures by error message to provide high-signal feedback."""
    if not failures:
        return "Total Failures: 0"

    error_counts = Counter(f.get("error", "Unknown error") for f in failures)
    lines: List[str] = [f"Total Failures: {len(failures)}", "Top Failure Patterns:"]

    for idx, (error_msg, count) in enumerate(error_counts.most_common(5), 1):
        examples = [f.get("test_case") for f in failures if f.get("error") == error_msg]
        lines.append(f"\n{idx}. Error ({count} occurrences): {error_msg}")
        for ex_idx, example_case in enumerate(examples[:5], 1):
            if not example_case:
                continue
            expected = example_case.get("expected_output", "N/A")
            display_case = {k: v for k, v in example_case.items() if k != "expected_output"}
            lines.append(
                f"   Example {ex_idx}: Input={json.dumps(display_case)} | Expected={expected}"
            )
        if len(examples) > 5:
            lines.append(f"   ... and {len(examples) - 5} more similar failures")

    return "\n".join(lines)


PYTHON_ONLY_SYSTEM_PROMPT = (
    "You are a Python 3 code generator. You MUST write valid Python 3 syntax only. "
    "Use True/False/None (capitalized), not true/false/null (lowercase). "
    "Use and/or/not for logical operations, not &&/||/!. This is Python, NOT JavaScript."
)


CODE_GENERATION_PROMPT = """You are a Python 3 code generation agent. You MUST write valid Python 3 code ONLY.

⚠️ CRITICAL: This is PYTHON, NOT JavaScript. Use Python syntax exclusively:
- Booleans: `True` and `False` (capitalized), NEVER `true` or `false`
- Null value: `None` (capitalized), NEVER `null`
- Logical operators: `and`, `or`, `not`, NEVER `&&`, `||`, `!`
- Equality: `==`, NEVER `===`
- String quotes: Use single `'` or double `"` quotes

Your task is to write a Python function that implements the logic of a workflow diagram EXACTLY.

ASSUMPTIONS:
- Assume all inputs are valid and present (no defensive checks needed)
- Do NOT wrap logic in try/except for normal control flow

You will be provided with:
1. The original Workflow Image
2. A COMPLETE structured JSON analysis of the workflow including:
   - All inputs with their types, ranges, and descriptions
   - All decision points with exact conditions and branches
   - All workflow paths showing how inputs flow to outputs
   - All possible outputs
   (NOTE: JSON uses lowercase true/false/null, but your Python code MUST use True/False/None)
3. A list of VALID OUTPUTS (you must strictly adhere to these - output strings must match EXACTLY)

CRITICAL INSTRUCTIONS:
1. **Trace the workflow step-by-step**: Follow the decision points in the order they appear in the workflow
2. **Use exact input names**: Pay attention to the exact input field names from the workflow analysis
3. **Match output strings exactly**: Output strings must match the VALID OUTPUTS list EXACTLY (case-sensitive, exact wording)
4. **Handle all decision points**: Every decision point in the workflow analysis must be implemented
5. **Follow the workflow paths**: Use the workflow_paths to understand the complete flow from inputs to outputs
6. **Check conditions precisely**: Use the exact thresholds and conditions specified in decision_points

REQUIREMENTS:
- Function name: `determine_workflow_outcome`
- Input: `inputs` (dictionary)
- Return: A single string matching one of the VALID OUTPUTS EXACTLY
- Logic: Use explicit if/elif/else logic following the workflow decision tree structure
- Error Handling: Handle missing keys gracefully using .get() with appropriate defaults
- Structure: Code must be syntactically valid Python 3
- Input names: Use the exact input names from the workflow analysis (check the inputs array)

OUTPUT FORMAT:
Return ONLY the valid Python 3 code. No markdown. No explanations. No JavaScript syntax.
"""
