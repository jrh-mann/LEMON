from __future__ import annotations

from src.lemon.analysis.agent import WorkflowAnalyzer


def test_parse_json_best_effort_extracts_first_object():
    analyzer = WorkflowAnalyzer()
    text = 'prefix {"a": 1} suffix {"b": 2}'
    assert analyzer._parse_json_best_effort(text) == {"a": 1}


def test_parse_json_best_effort_handles_braces_in_strings():
    analyzer = WorkflowAnalyzer()
    text = 'noise {"a": "value { with } braces", "b": 2} trailer'
    assert analyzer._parse_json_best_effort(text) == {"a": "value { with } braces", "b": 2}
