"""Secure test harness using E2B."""

import json
import os
import re
from e2b_code_interpreter import Sandbox


def _json_to_python_literal(data):
    """Convert JSON-serializable data to Python literal string representation.
    
    This converts JSON-style true/false/null to Python True/False/None.
    """
    json_str = json.dumps(data)
    # Replace JSON booleans and null with Python equivalents
    # Use word boundaries to avoid replacing parts of strings
    json_str = re.sub(r'\btrue\b', 'True', json_str)
    json_str = re.sub(r'\bfalse\b', 'False', json_str)
    json_str = re.sub(r'\bnull\b', 'None', json_str)
    return json_str


class CodeTestHarness:
    """Test harness for executing generated code in secure sandbox."""
    
    def __init__(self, test_cases_file, valid_outputs):
        """Initialize test harness.
        
        Args:
            test_cases_file: Path to JSON file containing test cases
            valid_outputs: List of valid output strings
        """
        with open(test_cases_file) as f:
            self.test_cases = json.load(f)
        self.valid_outputs = valid_outputs

    def score(self, code: str):
        """Score code against test cases.
        
        Args:
            code: Python code string to test
            
        Returns:
            Dictionary with pass/fail statistics and failure details
        """
        # Wrap generated code with a test runner script
        # This script runs INSIDE the sandbox
        # Convert test_cases and valid_outputs to Python literal format (True/False/None, not true/false/null)
        test_cases_python = _json_to_python_literal(self.test_cases)
        valid_outputs_python = _json_to_python_literal(self.valid_outputs)
        
        full_script = f"""
import json
import traceback

# 1. The Generated Code

{code}

# 2. The Test Runner

test_cases = {test_cases_python}

valid_outputs = set({valid_outputs_python})

results = []

for tc in test_cases:
    try:
        outcome = determine_workflow_outcome(tc)
        
        # Check if test case has expected_output (labeled test case)
        expected_output = tc.get("expected_output")
        
        if expected_output is not None:
            # Compare against expected output
            passed = outcome == expected_output
            if passed:
                error_msg = None
            else:
                error_msg = f"Expected '{{expected_output}}', got '{{outcome}}'"
        else:
            # Fallback: just check if output is valid
            passed = outcome in valid_outputs
            if passed:
                error_msg = None
            else:
                valid_list = list(valid_outputs)[:3]
                error_msg = f"Invalid output: '{{outcome}}' (Expected one of {{valid_list}}...)"
        
        results.append({{
            "passed": passed, 
            "error": error_msg
        }})
    except Exception as e:
        # Capture the actual python error (KeyError, ValueError, etc)
        results.append({{"passed": False, "error": f"{{type(e).__name__}}: {{str(e)}}"}})

print(json.dumps(results))
"""

        # 3. Execute in Sandbox
        # Initialize sandbox (requires E2B_API_KEY in .env)
        try:
            # E2B reads API key from E2B_API_KEY environment variable automatically
            # If not set, it will raise an error
            api_key = os.getenv("E2B_API_KEY")
            if not api_key:
                return {
                    "passed": 0,
                    "total": len(self.test_cases),
                    "pass_rate": 0.0,
                    "failures": [{"error": "E2B_API_KEY not found in environment variables. Please set it in your .env file.", "test_case": {}}]
                }
            
            # Use Sandbox.create() instead of Sandbox() - this is the correct way to instantiate
            with Sandbox.create() as sandbox:
                # Run the script directly on the sandbox
                execution = sandbox.run_code(full_script)
                
                if execution.error:
                    # System error (syntax error in the generated code itself)
                    error_name = execution.error.name if hasattr(execution.error, 'name') else 'UnknownError'
                    error_value = execution.error.value if hasattr(execution.error, 'value') else str(execution.error)
                    
                    # Provide more helpful error messages
                    error_msg = f"Syntax/Runtime Error: {error_name}\n{error_value}"
                    
                    # Add specific guidance for common errors
                    if "false" in error_value.lower() or "true" in error_value.lower():
                        error_msg += "\n\n💡 This error suggests JavaScript-style syntax (true/false) was used instead of Python (True/False)."
                        error_msg += "\n   The code should have been auto-fixed, but this indicates the model is generating JavaScript syntax."
                    elif "null" in error_value.lower():
                        error_msg += "\n\n💡 This error suggests JavaScript-style syntax (null) was used instead of Python (None)."
                    elif "NameError" in error_name:
                        error_msg += f"\n\n💡 NameError: A variable or function name is not defined. Check for typos or missing definitions."
                    elif "SyntaxError" in error_name:
                        error_msg += f"\n\n💡 SyntaxError: The code has invalid Python syntax. Check for missing colons, parentheses, or incorrect operators."
                    elif "IndentationError" in error_name:
                        error_msg += f"\n\n💡 IndentationError: Python requires consistent indentation. Check for mixed tabs/spaces or incorrect indentation levels."
                    
                    return {
                        "passed": 0, 
                        "total": len(self.test_cases), 
                        "pass_rate": 0.0,
                        "failures": [{"error": error_msg, "test_case": {}}]
                    }
                    
                # Parse the JSON output from the print() statement inside the sandbox
                try:
                    if execution.logs.stdout:
                        results = json.loads(execution.logs.stdout[0])
                    else:
                        # Check if there's stderr output that might give us clues
                        stderr_info = ""
                        if hasattr(execution.logs, 'stderr') and execution.logs.stderr:
                            stderr_info = f"\n\nStderr output: {execution.logs.stderr[:200]}"
                        
                        return {
                            "passed": 0, "total": len(self.test_cases), "pass_rate": 0.0,
                            "failures": [{"error": f"Sandbox produced no output. The code may have failed silently or not printed results.{stderr_info}", "test_case": {}}]
                        }
                except (IndexError, json.JSONDecodeError) as e:
                    # Try to get the actual output for debugging
                    output_preview = ""
                    if hasattr(execution.logs, 'stdout') and execution.logs.stdout:
                        output_preview = f"\n\nOutput preview: {str(execution.logs.stdout)[:200]}"
                    
                    return {
                        "passed": 0, "total": len(self.test_cases), "pass_rate": 0.0,
                        "failures": [{"error": f"Sandbox output parsing error: {str(e)}\n\n💡 The test runner script may not have printed valid JSON.{output_preview}", "test_case": {}}]
                    }
                
                passed = sum(1 for r in results if r['passed'])
                
                # Re-attach test cases to failures for analysis
                failures = []
                for i, res in enumerate(results):
                    if not res['passed']:
                        failures.append({
                            "error": res['error'],
                            "test_case": self.test_cases[i]
                        })
                
                return {
                    "passed": passed,
                    "total": len(self.test_cases),
                    "pass_rate": passed / len(self.test_cases) if len(self.test_cases) > 0 else 0.0,
                    "failures": failures
                }
        except Exception as e:
            # Handle sandbox initialization or execution errors
            error_msg = f"Sandbox error: {str(e)}"
            
            # Add helpful context for common errors
            error_str = str(e).lower()
            if "api_key" in error_str or "authentication" in error_str:
                error_msg += "\n\n💡 This appears to be an authentication error. Check that E2B_API_KEY is set in your .env file."
            elif "connection" in error_str or "timeout" in error_str:
                error_msg += "\n\n💡 This appears to be a connection error. Check your internet connection and E2B service status."
            elif "sandbox" in error_str and "init" in error_str:
                error_msg += "\n\n💡 Sandbox initialization failed. This may be due to API configuration issues or service unavailability."
            
            return {
                "passed": 0,
                "total": len(self.test_cases),
                "pass_rate": 0.0,
                "failures": [{"error": error_msg, "test_case": {}}]
            }

