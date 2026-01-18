"""Helpers for constructing an orchestrator instance."""

from __future__ import annotations

from pathlib import Path

from .orchestrator import Orchestrator
from ..tools import AnalyzeWorkflowTool, AskImageTool, PublishLatestAnalysisTool, ToolRegistry


def build_orchestrator(repo_root: Path) -> Orchestrator:
    registry = ToolRegistry()
    registry.register(AnalyzeWorkflowTool(repo_root))
    registry.register(AskImageTool(repo_root))
    registry.register(PublishLatestAnalysisTool(repo_root))
    return Orchestrator(registry)
