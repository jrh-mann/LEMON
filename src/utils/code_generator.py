"""Legacy wrapper for code generation.

The core implementation has moved to `src.lemon.generation.generator.CodeGenerator`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from src.lemon.core.workflow import WorkflowAnalysis
from src.lemon.generation.generator import CodeGenerator, GenerationContext

CODE_GENERATION_PROMPT = """You are a Python 3 code generation agent. You MUST write valid Python 3 code ONLY.

⚠️ CRITICAL: This is PYTHON, NOT JavaScript. Use Python syntax exclusively:
- Booleans: `True` and `False` (capitalized), NEVER `true` or `false`
- Null value: `None` (capitalized), NEVER `null`
- Logical operators: `and`, `or`, `not`, NEVER `&&`, `||`, `!`
- Equality: `==`, NEVER `===`
- String quotes: Use single `'` or double `"` quotes

Your task is to write a Python function that implements the logic of a workflow diagram EXACTLY.

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

EXAMPLE OF CORRECT PYTHON SYNTAX:
```python
def determine_workflow_outcome(inputs):
    # Extract inputs with defaults
    input1 = inputs.get('input_name', default_value)
    
    # Follow workflow decision points in order
    if condition1:  # ✅ CORRECT - NOT: if condition1 == true
        if condition2:  # Nested decisions as per workflow
            return "Exact Output String"  # Must match VALID OUTPUTS exactly
        else:
            return "Another Exact Output"
    elif other_condition:  # ✅ CORRECT - NOT: elif other_condition == false
        return "Output String"
    else:
        return "Default Output"
```

OUTPUT FORMAT:
Return ONLY the valid Python 3 code. No markdown. No explanations. No JavaScript syntax.

"""


def analyze_failure_patterns(failures):
    # Kept for API compatibility; core implementation lives in `src.lemon`.
    return failures


def generate_workflow_code(
    workflow_image_path, workflow_data, valid_outputs, failures=None, test_cases_file=None
):
    """Generate workflow code (legacy API)."""
    gen = CodeGenerator(max_tokens=8192)
    analysis = WorkflowAnalysis.model_validate(workflow_data)
    ctx = GenerationContext(
        failures=failures,
        test_cases_file=Path(test_cases_file) if test_cases_file else None,
    )
    return gen.generate(
        workflow_image_path=Path(workflow_image_path),
        workflow_data=analysis,
        valid_outputs=list(valid_outputs),
        context=ctx,
    )


def _fix_common_syntax_issues(code: str) -> str:
    # Legacy no-op: normalization is done in `src.lemon.generation.formatter`.
    return code
