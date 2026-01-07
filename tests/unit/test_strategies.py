from __future__ import annotations

from src.lemon.testing.strategies import ComprehensiveStrategy, EdgeCasesStrategy, RandomStrategy


def test_random_strategy_generates_n_cases():
    inputs = [{"name": "x", "values": [1, 2, 3]}, {"name": "y", "values": ["a", "b"]}]
    cases = RandomStrategy(seed=0).generate(inputs, 25)
    assert len(cases) == 25
    assert all("x" in c and "y" in c for c in cases)


def test_edge_cases_strategy_includes_edges_first():
    inputs = [{"name": "x", "values": [0, 5, 10]}, {"name": "flag", "values": [True, False]}]
    cases = EdgeCasesStrategy(seed=0).generate(inputs, 10)
    assert len(cases) == 10
    assert all("x" in c and "flag" in c for c in cases)


def test_comprehensive_strategy_produces_combinations_when_small():
    inputs = [{"name": "x", "values": [1, 2]}, {"name": "y", "values": ["a", "b"]}]
    cases = ComprehensiveStrategy(seed=0).generate(inputs, 10)
    assert len(cases) == 4  # full cartesian product


