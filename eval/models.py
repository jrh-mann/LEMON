"""Model configurations and per-token pricing.

Pricing as of March 2026 (USD per 1M tokens).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ModelConfig:
    """Immutable model configuration."""

    model_id: str
    input_cost_per_mtok: float
    output_cost_per_mtok: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost in USD for a given token count."""
        return (
            input_tokens * self.input_cost_per_mtok / 1_000_000
            + output_tokens * self.output_cost_per_mtok / 1_000_000
        )


MODELS: Dict[str, ModelConfig] = {
    # Azure Foundry deployment names (no date suffix).
    "haiku": ModelConfig(
        model_id="claude-haiku-4-5",
        input_cost_per_mtok=1.00,
        output_cost_per_mtok=5.00,
    ),
    "sonnet": ModelConfig(
        model_id="claude-sonnet-4-6",
        input_cost_per_mtok=3.00,
        output_cost_per_mtok=15.00,
    ),
    "opus": ModelConfig(
        model_id="claude-opus-4-6",
        input_cost_per_mtok=5.00,
        output_cost_per_mtok=25.00,
    ),
}


def resolve_model(name: str) -> ModelConfig:
    """Resolve a short model name to its config. Raises KeyError if unknown."""
    if name not in MODELS:
        raise KeyError(f"Unknown model '{name}'. Available: {', '.join(MODELS)}")
    return MODELS[name]
