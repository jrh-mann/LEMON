"""Test generation strategies."""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from itertools import product
from typing import Any, Dict, List


class TestGenerationStrategy(ABC):
    @abstractmethod
    def generate(self, inputs: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
        raise NotImplementedError


class ComprehensiveStrategy(TestGenerationStrategy):
    """Try to cover all combinations of discrete values; fill remaining randomly."""

    def __init__(self, *, seed: int | None = None):
        self.seed = seed

    def generate(self, inputs: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
        rng = random.Random(self.seed)
        input_value_sets = {inp["name"]: inp["values"] for inp in inputs}

        discrete_inputs: Dict[str, List[Any]] = {}
        continuous_inputs: Dict[str, List[Any]] = {}
        for name, values in input_value_sets.items():
            if len(values) <= 10:
                discrete_inputs[name] = values
            else:
                continuous_inputs[name] = values

        total_combinations = 1
        for values in discrete_inputs.values():
            total_combinations *= max(1, len(values))

        test_cases: List[Dict[str, Any]] = []
        if total_combinations <= n and discrete_inputs:
            discrete_names = list(discrete_inputs.keys())
            discrete_value_lists = [discrete_inputs[k] for k in discrete_names]
            for combo in product(*discrete_value_lists):
                tc = dict(zip(discrete_names, combo))
                for cname, cvalues in continuous_inputs.items():
                    tc[cname] = rng.choice(cvalues)
                test_cases.append(tc)

            while len(test_cases) < n:
                tc = {k: rng.choice(v) for k, v in input_value_sets.items()}
                if tc not in test_cases:
                    test_cases.append(tc)
        else:
            # Too many combinations: seed with edge-ish cases then random fill.
            test_cases = EdgeCasesStrategy(seed=self.seed).generate(inputs, min(n // 2, 50))
            while len(test_cases) < n:
                tc = {k: rng.choice(v) for k, v in input_value_sets.items()}
                if tc not in test_cases:
                    test_cases.append(tc)

        return test_cases[:n]


class RandomStrategy(TestGenerationStrategy):
    """Uniform random sampling from each input's value set."""

    def __init__(self, *, seed: int | None = None):
        self.seed = seed

    def generate(self, inputs: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
        rng = random.Random(self.seed)
        input_value_sets = {inp["name"]: inp["values"] for inp in inputs}
        return [{k: rng.choice(v) for k, v in input_value_sets.items()} for _ in range(n)]


class EdgeCasesStrategy(TestGenerationStrategy):
    """Prefer min/max/boundary values for numeric inputs; include all categorical values."""

    def __init__(self, *, seed: int | None = None):
        self.seed = seed

    def generate(self, inputs: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
        rng = random.Random(self.seed)
        edge_values: Dict[str, List[Any]] = {}
        for inp in inputs:
            name = inp["name"]
            values = inp["values"]
            if values and all(isinstance(v, (int, float)) for v in values):
                sorted_vals = sorted(values)
                ev = [sorted_vals[0], sorted_vals[-1]]
                if len(sorted_vals) > 2:
                    ev.append(sorted_vals[len(sorted_vals) // 2])
                edge_values[name] = list(dict.fromkeys(ev))
            else:
                edge_values[name] = values

        names = list(edge_values.keys())
        lists = [edge_values[nm] for nm in names]

        test_cases: List[Dict[str, Any]] = []
        for combo in product(*lists):
            if len(test_cases) >= n:
                break
            test_cases.append(dict(zip(names, combo)))

        while len(test_cases) < n:
            tc = {nm: rng.choice(vals) for nm, vals in edge_values.items()}
            if tc not in test_cases:
                test_cases.append(tc)
        return test_cases[:n]
