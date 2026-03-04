"""Helpers for constructing an orchestrator instance."""

from __future__ import annotations

from .orchestrator import Orchestrator


def build_orchestrator() -> Orchestrator:
    """Build an Orchestrator.

    All tool dispatch goes through MCP — no local ToolRegistry needed.
    """
    return Orchestrator()
