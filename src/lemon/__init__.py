"""LEMON - Workflow diagram to deterministic code pipeline."""

from typing import TYPE_CHECKING

__all__ = ["Settings", "RefinementPipeline"]

if TYPE_CHECKING:
    from .config.settings import Settings
    from .core.pipeline import RefinementPipeline


def __getattr__(name: str):
    if name == "Settings":
        from .config.settings import Settings

        return Settings
    if name == "RefinementPipeline":
        from .core.pipeline import RefinementPipeline

        return RefinementPipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
