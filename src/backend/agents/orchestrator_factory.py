"""Helpers for constructing an orchestrator instance."""

from __future__ import annotations

from pathlib import Path

from .orchestrator import Orchestrator
from ..tools import build_tool_registry


def build_orchestrator(repo_root: Path) -> Orchestrator:
    registry = build_tool_registry(repo_root)
    return Orchestrator(registry)
