"""Validation case generation.

This module generates test cases for human validation from workflow
input specifications. The cases are designed to cover:
- Random values within ranges
- Boundary values
- All enum options
- Edge cases around decision thresholds
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from lemon.core.blocks import Workflow, InputBlock, InputType, DecisionBlock
from lemon.execution.conditions import ConditionEvaluator


def generate_case_id() -> str:
    """Generate a unique case ID."""
    return uuid4().hex[:8]


@dataclass
class ValidationCase:
    """A case to be validated by a human.

    The expected_output is intentionally NOT included here - that's
    what the human validator provides. We only store the inputs.
    """
    id: str
    inputs: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "inputs": self.inputs}


class CaseGenerator:
    """Generates validation cases from workflow specifications.

    Strategies:
    - random: Random values within constraints
    - boundary: Values at and near boundaries
    - comprehensive: Combination of random, boundary, and enumeration

    Usage:
        generator = CaseGenerator(seed=42)  # For reproducibility
        cases = generator.generate(workflow, count=20)
        boundary_cases = generator.generate_boundary(workflow)
    """

    def __init__(self, seed: Optional[int] = None):
        """Initialize generator.

        Args:
            seed: Random seed for reproducibility. If None, random.
        """
        self.rng = random.Random(seed)
        self.condition_evaluator = ConditionEvaluator()

    def generate(self, workflow: Workflow, count: int = 20) -> List[ValidationCase]:
        """Generate random validation cases.

        Args:
            workflow: The workflow to generate cases for.
            count: Number of cases to generate.

        Returns:
            List of validation cases.
        """
        cases = []
        input_blocks = workflow.input_blocks

        for _ in range(count):
            inputs = {}
            for block in input_blocks:
                inputs[block.name] = self._generate_value(block)

            cases.append(ValidationCase(
                id=generate_case_id(),
                inputs=inputs,
            ))

        return cases

    def generate_boundary(self, workflow: Workflow) -> List[ValidationCase]:
        """Generate boundary/edge test cases.

        This generates cases at:
        - Min/max values for numeric inputs
        - Values just above/below decision thresholds
        - All enum values

        Args:
            workflow: The workflow to generate cases for.

        Returns:
            List of boundary cases.
        """
        cases = []
        input_blocks = workflow.input_blocks

        # Extract decision thresholds
        thresholds = self._extract_thresholds(workflow)

        # Generate min/max cases
        base_inputs = {b.name: self._generate_value(b) for b in input_blocks}

        # For each input, generate boundary cases
        for block in input_blocks:
            boundary_values = self._get_boundary_values(block, thresholds)

            for value in boundary_values:
                inputs = base_inputs.copy()
                inputs[block.name] = value
                cases.append(ValidationCase(
                    id=generate_case_id(),
                    inputs=inputs,
                ))

        return cases

    def generate_comprehensive(
        self,
        workflow: Workflow,
        random_count: int = 10,
    ) -> List[ValidationCase]:
        """Generate comprehensive test cases.

        Combines random, boundary, and enumeration strategies.

        Args:
            workflow: The workflow to generate cases for.
            random_count: Number of random cases to include.

        Returns:
            List of comprehensive cases.
        """
        cases = []

        # Add boundary cases
        cases.extend(self.generate_boundary(workflow))

        # Add random cases
        cases.extend(self.generate(workflow, count=random_count))

        # Deduplicate (by input values)
        seen: Set[str] = set()
        unique_cases = []
        for case in cases:
            key = str(sorted(case.inputs.items()))
            if key not in seen:
                seen.add(key)
                unique_cases.append(case)

        return unique_cases

    # -------------------------------------------------------------------------
    # Value Generation
    # -------------------------------------------------------------------------

    def _generate_value(self, block: InputBlock) -> Any:
        """Generate a random value for an input block."""
        if block.input_type == InputType.INT:
            min_val = int(block.range.min) if block.range and block.range.min is not None else 0
            max_val = int(block.range.max) if block.range and block.range.max is not None else 100
            return self.rng.randint(min_val, max_val)

        elif block.input_type == InputType.FLOAT:
            min_val = float(block.range.min) if block.range and block.range.min is not None else 0.0
            max_val = float(block.range.max) if block.range and block.range.max is not None else 100.0
            return round(self.rng.uniform(min_val, max_val), 2)

        elif block.input_type == InputType.BOOL:
            return self.rng.choice([True, False])

        elif block.input_type == InputType.STRING:
            return f"test_string_{self.rng.randint(1, 1000)}"

        elif block.input_type == InputType.ENUM:
            if block.enum_values:
                return self.rng.choice(block.enum_values)
            return "unknown"

        elif block.input_type == InputType.DATE:
            # Generate a date string
            year = self.rng.randint(1950, 2030)
            month = self.rng.randint(1, 12)
            day = self.rng.randint(1, 28)
            return f"{year:04d}-{month:02d}-{day:02d}"

        else:
            return None

    def _get_boundary_values(
        self,
        block: InputBlock,
        thresholds: Dict[str, List[float]],
    ) -> List[Any]:
        """Get boundary values for an input block."""
        values = []

        if block.input_type == InputType.INT:
            # Min/max from range
            if block.range:
                if block.range.min is not None:
                    values.append(int(block.range.min))
                if block.range.max is not None:
                    values.append(int(block.range.max))

            # Threshold values
            if block.name in thresholds:
                for threshold in thresholds[block.name]:
                    t = int(threshold)
                    values.extend([t - 1, t, t + 1])

        elif block.input_type == InputType.FLOAT:
            # Min/max from range
            if block.range:
                if block.range.min is not None:
                    values.append(float(block.range.min))
                if block.range.max is not None:
                    values.append(float(block.range.max))

            # Threshold values
            if block.name in thresholds:
                for threshold in thresholds[block.name]:
                    values.extend([threshold - 0.1, threshold, threshold + 0.1])

        elif block.input_type == InputType.BOOL:
            values = [True, False]

        elif block.input_type == InputType.ENUM:
            if block.enum_values:
                values = list(block.enum_values)

        # Remove duplicates and filter by range
        unique = []
        seen: Set[Any] = set()
        for v in values:
            if v not in seen:
                # Check range for numeric types
                if block.input_type in (InputType.INT, InputType.FLOAT) and block.range:
                    if block.range.min is not None and v < block.range.min:
                        continue
                    if block.range.max is not None and v > block.range.max:
                        continue
                seen.add(v)
                unique.append(v)

        return unique

    def _extract_thresholds(self, workflow: Workflow) -> Dict[str, List[float]]:
        """Extract numeric thresholds from decision conditions.

        Parses conditions like "age >= 18" to extract {age: [18]}.
        """
        thresholds: Dict[str, List[float]] = {}

        for block in workflow.decision_blocks:
            # Get referenced variables
            vars = self.condition_evaluator.get_referenced_variables(block.condition)

            # Try to extract numbers from condition
            numbers = self._extract_numbers(block.condition)

            # Associate numbers with variables (heuristic)
            for var in vars:
                if var not in thresholds:
                    thresholds[var] = []
                thresholds[var].extend(numbers)

        return thresholds

    def _extract_numbers(self, condition: str) -> List[float]:
        """Extract numeric literals from a condition string."""
        import re
        # Match integers and floats
        pattern = r'[-+]?\d+\.?\d*'
        matches = re.findall(pattern, condition)
        return [float(m) for m in matches if m]
