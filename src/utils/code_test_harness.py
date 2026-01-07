"""Legacy wrapper for secure test harness using E2B.

Core implementation now lives in `src.lemon.testing.harness.TestHarness`.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List

from src.lemon.testing.harness import TestHarness


def _json_to_python_literal(data: Any) -> str:
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
    
    def __init__(self, test_cases_file: str, valid_outputs: List[str]):
        """Initialize test harness.
        
        Args:
            test_cases_file: Path to JSON file containing test cases
            valid_outputs: List of valid output strings
        """
        with open(test_cases_file) as f:
            self.test_cases = json.load(f)
        self.valid_outputs = valid_outputs

    def score(self, code: str) -> Dict[str, Any]:
        """Score code against test cases.
        
        Args:
            code: Python code string to test
            
        Returns:
            Dictionary with pass/fail statistics and failure details
        """
        harness = TestHarness(test_cases=self.test_cases, valid_outputs=self.valid_outputs)
        results = harness.score(code)
        return {
            "passed": results.passed,
            "total": results.total,
            "pass_rate": results.pass_rate,
            "failures": [{"error": f.error, "test_case": f.test_case} for f in results.failures],
        }

