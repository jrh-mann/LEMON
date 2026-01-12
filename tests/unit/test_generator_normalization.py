from __future__ import annotations

import json

from src.lemon.testing.generator import TestCaseGenerator


def test_normalize_output_requires_exact_match(tmp_path):
    inputs_path = tmp_path / "inputs.json"
    inputs_path.write_text(
        json.dumps(
            [
                {
                    "input_name": "x",
                    "input_type": "Int",
                    "range": {"min": 0, "max": 1},
                    "description": "",
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    generator = TestCaseGenerator(str(inputs_path))
    valid_outputs = ["Yes", "No"]

    assert generator._normalize_output(" Yes ", valid_outputs) == "Yes"
    assert generator._normalize_output("yes", valid_outputs) is None
