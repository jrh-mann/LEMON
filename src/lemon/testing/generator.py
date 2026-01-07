"""Test case generation and labeling."""

from __future__ import annotations

import json
import os
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image

from ..core.workflow import StandardizedInput
from ..utils.logging import get_logger
from .strategies import ComprehensiveStrategy, EdgeCasesStrategy, RandomStrategy, TestGenerationStrategy

logger = get_logger(__name__)


@dataclass(frozen=True)
class TestCase:
    inputs: Dict[str, Any]
    expected_output: str | None = None


class TestCaseGenerator:
    """Generate and label test cases from `workflow_inputs.json`."""

    def __init__(self, inputs_file: str = "workflow_inputs.json"):
        self.inputs_file = Path(inputs_file)
        self.inputs = self._load_inputs()

    def _load_inputs(self) -> List[StandardizedInput]:
        if not self.inputs_file.exists():
            raise FileNotFoundError(f"Inputs file not found: {self.inputs_file}")
        with open(self.inputs_file, "r") as f:
            raw = json.load(f)
        return [StandardizedInput.model_validate(x) for x in raw]

    def generate_test_cases(self, n: int, strategy: str = "comprehensive", seed: int | None = None) -> List[Dict[str, Any]]:
        """Generate N input dictionaries according to strategy."""
        value_specs = [{"name": inp.input_name, "values": self._generate_values_for_input(inp)} for inp in self.inputs]

        strat: TestGenerationStrategy
        if strategy == "comprehensive":
            strat = ComprehensiveStrategy(seed=seed)
        elif strategy == "random":
            strat = RandomStrategy(seed=seed)
        elif strategy == "edge_cases":
            strat = EdgeCasesStrategy(seed=seed)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        return strat.generate(value_specs, n)

    def save_test_cases(self, test_cases: List[Dict[str, Any]], output_file: str = "test_cases.json") -> None:
        output_path = Path(output_file)
        with open(output_path, "w") as f:
            json.dump(test_cases, f, indent=2)
        logger.info("Saved test cases", extra={"count": len(test_cases), "path": str(output_path)})

    def label_test_cases(
        self,
        *,
        test_cases: List[Dict[str, Any]],
        workflow_image_path: str,
        valid_outputs: List[str],
        model: str | None = None,
        batch_size: int = 20,
    ) -> List[Dict[str, Any]]:
        """Label test cases with expected outputs using Claude (image + prompt)."""
        from src.utils.request_utils import make_image_request  # legacy module

        if model is None:
            model = os.getenv("HAIKU_DEPLOYMENT_NAME") or os.getenv("DEPLOYMENT_NAME", "haiku")

        logger.info("Labeling test cases", extra={"count": len(test_cases), "model": model, "batch_size": batch_size})

        img = Image.open(workflow_image_path)
        img_format = (img.format or "PNG").upper()
        format_map = {"JPEG": "PNG", "JPG": "PNG", "PNG": "PNG", "WEBP": "PNG", "GIF": "PNG"}
        format_str = format_map.get(img_format, "PNG")

        labeled: List[Dict[str, Any]] = []
        total_batches = (len(test_cases) + batch_size - 1) // batch_size

        for batch_idx in range(0, len(test_cases), batch_size):
            batch = test_cases[batch_idx : batch_idx + batch_size]
            batch_num = (batch_idx // batch_size) + 1
            logger.info("Processing batch", extra={"batch_num": batch_num, "total_batches": total_batches})

            prompt = self._create_labeling_prompt(batch, valid_outputs)
            try:
                response = make_image_request(
                    image=img,
                    prompt=prompt,
                    max_tokens=4096,
                    model=model,
                    image_format=format_str,
                )
                response_text = response.content[0].text if response.content else ""
                labeled.extend(self._parse_labeling_response(batch, response_text, valid_outputs))
            except Exception as e:
                logger.warning("Error labeling batch; leaving unlabeled", extra={"batch_num": batch_num, "error": str(e)})
                for tc in batch:
                    out = tc.copy()
                    out["expected_output"] = None
                    labeled.append(out)

        return labeled

    def _create_labeling_prompt(self, test_cases: List[Dict[str, Any]], valid_outputs: List[str]) -> str:
        test_cases_json = json.dumps(test_cases, indent=2)
        return f"""You are analyzing a workflow diagram. For each test case below, determine what the expected output should be according to the workflow.

VALID OUTPUTS (you must choose exactly one of these):
{json.dumps(valid_outputs, indent=2)}

TEST CASES TO LABEL:
{test_cases_json}

For each test case, determine the expected output by following the workflow logic shown in the image. The output must be EXACTLY one of the valid outputs listed above.

Return your response as a JSON array with the same length as the test cases array. Each element should be a string containing the expected output for that test case.

Return ONLY the JSON array, no other text."""

    def _parse_labeling_response(
        self, test_cases: List[Dict[str, Any]], response_text: str, valid_outputs: List[str]
    ) -> List[Dict[str, Any]]:
        json_match = re.search(r"\[.*\]", response_text, re.DOTALL)
        json_text = json_match.group(0) if json_match else response_text.strip()

        try:
            expected_outputs = json.loads(json_text)
            if not isinstance(expected_outputs, list):
                raise ValueError("Response is not a list")
        except Exception as e:
            logger.warning("Failed parsing labeling response", extra={"error": str(e), "preview": response_text[:200]})
            expected_outputs = [None] * len(test_cases)

        if len(expected_outputs) != len(test_cases):
            if len(expected_outputs) < len(test_cases):
                expected_outputs.extend([None] * (len(test_cases) - len(expected_outputs)))
            else:
                expected_outputs = expected_outputs[: len(test_cases)]

        labeled: List[Dict[str, Any]] = []
        for tc, expected in zip(test_cases, expected_outputs):
            out = tc.copy()
            out["expected_output"] = expected if expected in valid_outputs else None
            labeled.append(out)
        return labeled

    def _generate_values_for_input(self, inp: StandardizedInput, num_samples: int = 5) -> List[Any]:
        input_type = inp.input_type
        range_info = inp.range

        if input_type == "bool":
            return [True, False]

        if isinstance(range_info, list):
            return range_info

        if isinstance(range_info, dict):
            min_val = range_info.get("min")
            max_val = range_info.get("max")
            value = range_info.get("value")

            if value is not None:
                return [value]

            if input_type == "Int":
                if min_val is not None and max_val is not None:
                    values: List[Any] = [int(min_val), int(max_val)]
                    if max_val > min_val:
                        mid = (int(min_val) + int(max_val)) // 2
                        values.append(mid)
                        for _ in range(max(0, num_samples - 3)):
                            values.append(random.randint(int(min_val), int(max_val)))
                    return list(dict.fromkeys(values))
                if min_val is not None:
                    return [int(min_val), int(min_val) + 10, int(min_val) + 100]
                if max_val is not None:
                    return [int(max_val), int(max_val) - 10, int(max_val) - 100]
                return [0, 1, 10, 100, -1, -10]

            if input_type == "Float":
                if min_val is not None and max_val is not None:
                    values2: List[Any] = [float(min_val), float(max_val)]
                    if max_val > min_val:
                        midf = (float(min_val) + float(max_val)) / 2
                        values2.append(midf)
                        for _ in range(max(0, num_samples - 3)):
                            values2.append(random.uniform(float(min_val), float(max_val)))
                    # ensure JSON-serializable float values
                    return list(dict.fromkeys(values2))
                if min_val is not None:
                    return [float(min_val), float(min_val) + 0.1, float(min_val) + 1.0]
                if max_val is not None:
                    return [float(max_val), float(max_val) - 0.1, float(max_val) - 1.0]
                return [0.0, 0.1, 1.0, 10.0, -1.0, -10.0]

        if input_type == "str":
            return ["value1", "value2", "example", ""]
        if input_type == "date":
            return ["2024-01-01", "2024-06-15", "2024-12-31"]
        return [None]


