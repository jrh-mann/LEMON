from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest


@pytest.fixture()
def sample_workflow_analysis_dict() -> Dict[str, Any]:
    return {
        "workflow_description": "Simple workflow",
        "domain": "demo",
        "inputs": [
            {
                "name": "age",
                "type": "numeric",
                "format": "integer",
                "possible_values": {"type": "range", "min": 0, "max": 100, "unit": "years"},
                "required_at": "start",
                "used_at": ["age_check"],
                "description": "Age in years",
                "constraints": "0-100",
            },
            {
                "name": "smoker",
                "type": "boolean",
                "format": "boolean",
                "possible_values": {"type": "enum", "values": [True, False]},
                "required_at": "start",
                "used_at": ["risk_check"],
                "description": "Smoking status",
                "constraints": "",
            },
        ],
        "decision_points": [
            {
                "name": "age_check",
                "description": "Age gate",
                "condition": "age >= 18",
                "inputs_required": ["age"],
                "branches": [
                    {"condition": ">=18", "outcome": "adult", "leads_to": "risk_check"},
                    {"condition": "<18", "outcome": "minor", "leads_to": "OutputMinor"},
                ],
            }
        ],
        "outputs": [{"name": "OutputMinor", "type": "text", "description": "Minor", "produced_by": ["path_1"]}],
        "workflow_paths": [
            {
                "path_id": "path_1",
                "description": "Minor path",
                "required_inputs": ["age"],
                "decision_sequence": ["age_check -> <18"],
                "output": "OutputMinor",
            }
        ],
    }


@pytest.fixture()
def tmp_workflow_inputs_file(tmp_path: Path) -> Path:
    p = tmp_path / "workflow_inputs.json"
    p.write_text(
        """[
  {"input_name": "age", "input_type": "Int", "range": {"min": 0, "max": 100}, "description": "Age"},
  {"input_name": "smoker", "input_type": "bool", "range": null, "description": "Smoker"}
]""",
        encoding="utf-8",
    )
    return p


