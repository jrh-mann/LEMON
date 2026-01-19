"""Helpers for constructing an orchestrator instance."""

from __future__ import annotations

from pathlib import Path

from .orchestrator import Orchestrator
from ..tools import (
    AnalyzeWorkflowTool,
    PublishLatestAnalysisTool,
    GetCurrentWorkflowTool,
    AddNodeTool,
    ModifyNodeTool,
    DeleteNodeTool,
    AddConnectionTool,
    DeleteConnectionTool,
    BatchEditWorkflowTool,
    ToolRegistry,
)


def build_orchestrator(repo_root: Path) -> Orchestrator:
    registry = ToolRegistry()

    # Workflow analysis tools
    registry.register(AnalyzeWorkflowTool(repo_root))
    registry.register(PublishLatestAnalysisTool(repo_root))

    # Workflow manipulation tools
    registry.register(GetCurrentWorkflowTool())
    registry.register(AddNodeTool())
    registry.register(ModifyNodeTool())
    registry.register(DeleteNodeTool())
    registry.register(AddConnectionTool())
    registry.register(DeleteConnectionTool())
    registry.register(BatchEditWorkflowTool())

    return Orchestrator(registry)
