"""Legacy wrapper for test case generation.

Core implementation now lives in `src.lemon.testing.generator.TestCaseGenerator`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.lemon.testing.generator import TestCaseGenerator as CoreTestCaseGenerator


class TestCaseGenerator:
    def __init__(self, inputs_file: str = "workflow_inputs.json"):
        self._core = CoreTestCaseGenerator(inputs_file=inputs_file)

    def generate_test_cases(
        self, n: int, strategy: str = "comprehensive", seed: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        return self._core.generate_test_cases(n, strategy=strategy, seed=seed)

    def save_test_cases(
        self, test_cases: List[Dict[str, Any]], output_file: str = "test_cases.json"
    ) -> None:
        self._core.save_test_cases(test_cases, output_file=output_file)

    def label_test_cases(
        self,
        test_cases: List[Dict[str, Any]],
        workflow_image_path: str,
        valid_outputs: List[str],
        model: Optional[str] = None,
        batch_size: int = 20,
    ) -> List[Dict[str, Any]]:
        return self._core.label_test_cases(
            test_cases=test_cases,
            workflow_image_path=workflow_image_path,
            valid_outputs=valid_outputs,
            model=model,
            batch_size=batch_size,
        )


def generate_test_cases_from_file(
    inputs_file: str = "workflow_inputs.json",
    n: int = 100,
    strategy: str = "comprehensive",
    output_file: str = "test_cases.json",
    seed: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Convenience function to generate test cases from inputs file.

    Args:
        inputs_file: Path to workflow inputs JSON file
        n: Number of test cases to generate
        strategy: Generation strategy ("comprehensive", "random", "edge_cases")
        output_file: Path to save test cases
        seed: Random seed for reproducibility

    Returns:
        List of test case dictionaries
    """
    generator = TestCaseGenerator(inputs_file)
    test_cases = generator.generate_test_cases(n, strategy=strategy, seed=seed)
    generator.save_test_cases(test_cases, output_file)
    return test_cases
