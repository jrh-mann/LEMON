from __future__ import annotations

from src.lemon.generation.validator import has_entrypoint_function


def test_validator_detects_entrypoint():
    code = "def determine_workflow_outcome(inputs):\n    return 'x'\n"
    assert has_entrypoint_function(code) is True


def test_validator_rejects_missing_entrypoint():
    code = "def something_else():\n    return 1\n"
    assert has_entrypoint_function(code) is False


