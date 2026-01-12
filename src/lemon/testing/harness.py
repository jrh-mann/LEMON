"""Secure test harness (E2B sandbox)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List

from e2b_code_interpreter import Sandbox

from ..utils.logging import get_logger

logger = get_logger(__name__)


def _normalize_output(output: Any) -> str:
    """Normalize output for comparison: trim surrounding whitespace."""
    if output is None:
        return ""
    if isinstance(output, str):
        return output.strip()
    return str(output).strip()


@dataclass(frozen=True)
class TestFailure:
    error: str
    test_case: Dict[str, Any]


@dataclass(frozen=True)
class TestResults:
    passed: int
    total: int
    failures: List[TestFailure]

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


class TestHarness:
    """Executes generated code against test cases in an isolated sandbox."""

    def __init__(self, *, test_cases: List[Dict[str, Any]], valid_outputs: List[str]):
        self.test_cases = test_cases
        self.valid_outputs = valid_outputs

    @classmethod
    def from_file(cls, *, test_cases_file: str, valid_outputs: List[str]) -> "TestHarness":
        with open(test_cases_file) as f:
            test_cases = json.load(f)
        return cls(test_cases=test_cases, valid_outputs=valid_outputs)

    def score(self, code: str) -> TestResults:
        test_cases_python = _json_to_python_literal(self.test_cases)
        valid_outputs_python = _json_to_python_literal(self.valid_outputs)

        full_script = f"""
import json
def normalize_output(output):
    \"\"\"Normalize output for comparison: trim surrounding whitespace.\"\"\"
    if output is None:
        return ""
    if isinstance(output, str):
        return output.strip()
    return str(output).strip()

{code}

test_cases = {test_cases_python}
valid_outputs = set({valid_outputs_python})

results = []
for tc in test_cases:
    try:
        outcome = determine_workflow_outcome(tc)
        expected_output = tc.get("expected_output")
        if expected_output is not None:
            # Normalize both for comparison
            outcome_norm = normalize_output(outcome)
            expected_norm = normalize_output(expected_output)
            passed = outcome_norm == expected_norm
            error_msg = None if passed else f"Expected '{{expected_output}}', got '{{outcome}}'"
        else:
            # Check against valid outputs (normalized)
            outcome_norm = normalize_output(outcome)
            valid_norm = [normalize_output(v) for v in valid_outputs]
            passed = outcome_norm in valid_norm
            error_msg = None if passed else f"Invalid output: '{{outcome}}'"
        results.append({{"passed": passed, "error": error_msg}})
    except Exception as e:
        results.append({{"passed": False, "error": f"{{type(e).__name__}}: {{str(e)}}"}})

print(json.dumps(results))
"""

        api_key = os.getenv("E2B_API_KEY")
        if not api_key:
            missing_key_failures = [
                TestFailure(
                    error="E2B_API_KEY not found in environment variables. Please set it in your .env file.",
                    test_case={},
                )
            ]
            return TestResults(passed=0, total=len(self.test_cases), failures=missing_key_failures)

        try:
            with Sandbox.create() as sandbox:
                execution = sandbox.run_code(full_script)
                if execution.error:
                    error_name = getattr(execution.error, "name", "UnknownError")
                    error_value = getattr(execution.error, "value", str(execution.error))
                    msg = f"Syntax/Runtime Error: {error_name}\n{error_value}"
                    runtime_failures = [TestFailure(error=msg, test_case={})]
                    return TestResults(
                        passed=0, total=len(self.test_cases), failures=runtime_failures
                    )

                if not execution.logs.stdout:
                    no_output_failures = [
                        TestFailure(error="Sandbox produced no output.", test_case={})
                    ]
                    return TestResults(
                        passed=0, total=len(self.test_cases), failures=no_output_failures
                    )

                results = json.loads(execution.logs.stdout[0])
                passed = sum(1 for r in results if r.get("passed"))
                failures: List[TestFailure] = []
                for i, res in enumerate(results):
                    if not res.get("passed"):
                        failures.append(
                            TestFailure(
                                error=res.get("error") or "Unknown error",
                                test_case=self.test_cases[i],
                            )
                        )
                return TestResults(passed=passed, total=len(self.test_cases), failures=failures)
        except Exception as e:
            sandbox_failures = [TestFailure(error=f"Sandbox error: {str(e)}", test_case={})]
            return TestResults(passed=0, total=len(self.test_cases), failures=sandbox_failures)


def _json_to_python_literal(data: Any) -> str:
    """Convert JSON-serializable data to a Python literal string."""
    json_str = json.dumps(data)
    json_str = re.sub(r"\btrue\b", "True", json_str)
    json_str = re.sub(r"\bfalse\b", "False", json_str)
    json_str = re.sub(r"\bnull\b", "None", json_str)
    return json_str
