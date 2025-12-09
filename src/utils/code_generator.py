"""Generate Python code from workflow analysis with smart failure analysis."""

import json
from collections import Counter
from .request_utils import make_request, image_to_base64
from PIL import Image

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
2. A structured JSON analysis of the workflow (NOTE: JSON uses lowercase true/false/null, but your Python code MUST use True/False/None)
3. A list of VALID OUTPUTS (you must strictly adhere to these)

REQUIREMENTS:
- Function name: `determine_workflow_outcome`
- Input: `inputs` (dictionary)
- Return: A single string matching one of the VALID OUTPUTS
- Logic: Use explicit if/elif/else logic. No ML or fuzzy matching
- Error Handling: Handle missing keys gracefully (e.g., use .get() or check existence)
- Structure: Code must be syntactically valid Python 3

EXAMPLE OF CORRECT PYTHON SYNTAX:
```python
if condition is True:  # ✅ CORRECT - NOT: if condition == true
    return "output"
elif other_condition is False:  # ✅ CORRECT - NOT: elif other_condition == false
    return None  # ✅ CORRECT - NOT: return null
else:
    if value is None:  # ✅ CORRECT - NOT: if value == null
        return "default"
```

OUTPUT FORMAT:
Return ONLY the valid Python 3 code. No markdown. No explanations. No JavaScript syntax.

"""


def analyze_failure_patterns(failures):
    """Group failures by error message to provide high-signal feedback."""
    if not failures:
        return None
        
    # Group by error message
    error_counts = Counter(f['error'] for f in failures)
    
    analysis = []
    analysis.append(f"Total Failures: {len(failures)}")
    analysis.append("Top Failure Patterns:")
    
    # Get top 3 most common errors
    for error_msg, count in error_counts.most_common(3):
        # Find one example test case for this error
        # Handle case where test_case might be missing or None
        examples = [f.get('test_case') for f in failures if f['error'] == error_msg]
        example_case = examples[0] if examples else "N/A"
        
        analysis.append(f"\n1. Error ({count} occurrences): {error_msg}")
        analysis.append(f"   Caused by input: {json.dumps(example_case)}")
        
    return "\n".join(analysis)


def generate_workflow_code(workflow_image_path, workflow_data, valid_outputs, failures=None):
    """Generate Python code implementing the workflow logic.
    
    Args:
        workflow_image_path: Path to workflow image
        workflow_data: Structured JSON analysis of workflow
        valid_outputs: List of valid output strings
        failures: Optional list of failure dictionaries from previous test runs
        
    Returns:
        Python code as string
    """
    img = Image.open(workflow_image_path)
    
    # Determine image format and media type
    img_format = img.format or 'PNG'
    format_map = {
        'JPEG': ('PNG', 'image/png'),  # Convert JPEG to PNG for consistency
        'JPG': ('PNG', 'image/png'),
        'PNG': ('PNG', 'image/png'),
        'WEBP': ('PNG', 'image/png'),
        'GIF': ('PNG', 'image/png'),
    }
    format_str, media_type = format_map.get(img_format.upper(), ('PNG', 'image/png'))
    
    img_base64 = image_to_base64(img, format=format_str)
    
    context = f"WORKFLOW ANALYSIS:\n{json.dumps(workflow_data, indent=2)}\n\nVALID OUTPUTS:\n{json.dumps(valid_outputs, indent=2)}"
    if failures:
        # Use the smart analysis instead of raw dump
        failure_report = analyze_failure_patterns(failures)
        context += f"\n\nCRITICAL FEEDBACK - FIX THESE ISSUES:\n{failure_report}\n\nAnalyze why these specific inputs caused these errors and fix the logic."
    
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_base64}},
                {"type": "text", "text": CODE_GENERATION_PROMPT + "\n\nCONTEXT:\n" + context}
            ]
        }
    ]
    
    response = make_request(
        messages, 
        max_tokens=4096, 
        system="You are a Python 3 code generator. You MUST write valid Python 3 syntax only. Use True/False/None (capitalized), not true/false/null (lowercase). Use and/or/not for logical operations, not &&/||/!. This is Python, NOT JavaScript."
    )
    code = response.content[0].text
    
    # Clean up markdown code blocks if present
    code = code.replace("```python", "").replace("```", "").strip()
    
    # Post-process to fix common syntax issues
    code = _fix_common_syntax_issues(code)
    
    # Validate that we didn't miss any JavaScript syntax (double-check)
    import re
    js_issues = []
    
    if re.search(r'\bfalse\b', code):
        js_issues.append("'false' (should be 'False')")
        code = re.sub(r'\bfalse\b', 'False', code)
    if re.search(r'\btrue\b', code):
        js_issues.append("'true' (should be 'True')")
        code = re.sub(r'\btrue\b', 'True', code)
    if re.search(r'\bnull\b', code):
        js_issues.append("'null' (should be 'None')")
        code = re.sub(r'\bnull\b', 'None', code)
    
    if js_issues:
        print(f"   ⚠️ Warning: Found JavaScript syntax in generated code: {', '.join(js_issues)}")
        print("   🔧 Auto-fixed, but this suggests the model is generating JavaScript-style syntax.")
        print("   💡 Consider reviewing the prompt or model configuration.")
    
    return code


def _fix_common_syntax_issues(code: str) -> str:
    """Fix common syntax issues in generated code.
    
    Args:
        code: Generated Python code string
        
    Returns:
        Fixed code string
    """
    import re
    
    # Track if we made any fixes
    original_code = code
    
    # Fix JavaScript-style booleans
    # Replace standalone 'false' and 'true' (but not in strings or variable names)
    # Use word boundaries to avoid replacing parts of variable names
    # Be more aggressive - replace even if it's part of a larger expression
    code = re.sub(r'\bfalse\b', 'False', code)
    code = re.sub(r'\btrue\b', 'True', code)
    
    # Fix JavaScript-style null
    code = re.sub(r'\bnull\b', 'None', code)
    
    # Fix JavaScript-style logical operators
    # Replace && with and (with spaces around it)
    code = re.sub(r'\s+&&\s+', ' and ', code)
    code = re.sub(r'\s+&&', ' and', code)
    code = re.sub(r'&&\s+', 'and ', code)
    code = re.sub(r'&&', ' and ', code)
    
    # Replace || with or
    code = re.sub(r'\s+\|\|\s+', ' or ', code)
    code = re.sub(r'\s+\|\|', ' or', code)
    code = re.sub(r'\|\|\s+', 'or ', code)
    code = re.sub(r'\|\|', ' or ', code)
    
    # Fix ! at start of conditions (but not !=)
    # Match ! followed by non-whitespace, non-= character
    code = re.sub(r'!([^=\s])', r'not \1', code)
    # Also handle ! with whitespace after
    code = re.sub(r'!\s+', 'not ', code)
    
    # Check if we made changes and warn
    if code != original_code:
        # Count how many fixes we made
        false_count = len(re.findall(r'\bfalse\b', original_code))
        true_count = len(re.findall(r'\btrue\b', original_code))
        null_count = len(re.findall(r'\bnull\b', original_code))
        if false_count > 0 or true_count > 0 or null_count > 0:
            print(f"   ⚠️ Fixed JavaScript syntax: {false_count} false→False, {true_count} true→True, {null_count} null→None")
    
    return code

