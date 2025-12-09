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
    """Group failures by error message to provide high-signal feedback."""
    if not failures:
        return None
        
    # Group by error message
    error_counts = Counter(f['error'] for f in failures)
    
    analysis = []
    analysis.append(f"Total Failures: {len(failures)}")
    analysis.append("Top Failure Patterns:")
    
    # Get top 5 most common errors (increased from 3)
    for error_msg, count in error_counts.most_common(5):
        # Find multiple examples for this error (up to 5)
        examples = [f.get('test_case') for f in failures if f['error'] == error_msg]
        
        analysis.append(f"\n1. Error ({count} occurrences): {error_msg}")
        
        # Show up to 5 examples per error pattern
        for i, example_case in enumerate(examples[:5], 1):
            if example_case:
                # Extract expected_output if present
                expected = example_case.get('expected_output', 'N/A')
                # Remove expected_output from display to show just inputs
                display_case = {k: v for k, v in example_case.items() if k != 'expected_output'}
                analysis.append(f"   Example {i}: Input={json.dumps(display_case)} | Expected={expected}")
        
        if len(examples) > 5:
            analysis.append(f"   ... and {len(examples) - 5} more similar failures")
        
    return "\n".join(analysis)


def generate_workflow_code(workflow_image_path, workflow_data, valid_outputs, failures=None, test_cases_file=None):
    """Generate Python code implementing the workflow logic.
    
    Args:
        workflow_image_path: Path to workflow image
        workflow_data: Structured JSON analysis of workflow (should include full analysis with decision_points, workflow_paths, etc.)
        valid_outputs: List of valid output strings
        failures: Optional list of failure dictionaries from previous test runs
        test_cases_file: Optional path to test cases file to extract input names
        
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
    
    # Build comprehensive context
    context_parts = []
    
    # 1. Full workflow analysis (this is the key improvement - dump everything)
    context_parts.append("=" * 80)
    context_parts.append("COMPLETE WORKFLOW ANALYSIS")
    context_parts.append("=" * 80)
    context_parts.append(json.dumps(workflow_data, indent=2))
    
    # 2. Extract and show actual input names from test cases if available
    if test_cases_file:
        try:
            with open(test_cases_file) as f:
                test_cases = json.load(f)
            if test_cases:
                # Get all unique input names from test cases
                input_names = set()
                for tc in test_cases[:10]:  # Check first 10 test cases
                    for key in tc.keys():
                        if key != 'expected_output':
                            input_names.add(key)
                
                if input_names:
                    context_parts.append("\n" + "=" * 80)
                    context_parts.append("ACTUAL INPUT NAMES FROM TEST CASES")
                    context_parts.append("=" * 80)
                    context_parts.append("Use these EXACT input names in your code:")
                    context_parts.append(json.dumps(sorted(list(input_names)), indent=2))
        except Exception as e:
            pass  # If we can't load test cases, continue without them
    
    # 3. Valid outputs
    context_parts.append("\n" + "=" * 80)
    context_parts.append("VALID OUTPUTS (MUST MATCH EXACTLY)")
    context_parts.append("=" * 80)
    context_parts.append(json.dumps(valid_outputs, indent=2))
    
    # 4. Failure feedback if available
    if failures:
        failure_report = analyze_failure_patterns(failures)
        context_parts.append("\n" + "=" * 80)
        context_parts.append("CRITICAL FEEDBACK - FIX THESE ISSUES")
        context_parts.append("=" * 80)
        context_parts.append(failure_report)
        context_parts.append("\nINSTRUCTIONS:")
        context_parts.append("- Analyze why these specific inputs caused these errors")
        context_parts.append("- Check if you're using the correct input names")
        context_parts.append("- Verify your conditions match the workflow decision points")
        context_parts.append("- Ensure output strings match the VALID OUTPUTS exactly")
        context_parts.append("- Trace through the workflow_paths to understand the correct flow")
    
    context = "\n".join(context_parts)
    
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
        max_tokens=8192,  # Increased to handle full workflow analysis
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

