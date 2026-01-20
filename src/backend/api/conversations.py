"""Conversation state and orchestrator wiring."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from uuid import uuid4
from pathlib import Path

from .common import utc_now
from ..agents.orchestrator import Orchestrator
from ..agents.orchestrator_factory import build_orchestrator


@dataclass
class Conversation:
    id: str
    orchestrator: Orchestrator
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    workflow_state: Dict[str, Any] = field(default_factory=lambda: {"nodes": [], "edges": []})
    workflow_analysis: Dict[str, Any] = field(default_factory=lambda: {"inputs": [], "outputs": []})

    def update_workflow_state(self, workflow: Dict[str, Any]) -> None:
        """Update workflow state (single source of truth).

        Args:
            workflow: Complete workflow with nodes and edges
        """
        if not isinstance(workflow, dict):
            return

        self.workflow_state = {
            "nodes": workflow.get("nodes", []),
            "edges": workflow.get("edges", []),
        }
        self.updated_at = utc_now()

    def update_workflow_analysis(self, analysis: Dict[str, Any]) -> None:
        """Update workflow analysis (inputs and outputs).

        Args:
            analysis: Workflow analysis with inputs and outputs
        """
        if not isinstance(analysis, dict):
            return

        self.workflow_analysis = {
            "inputs": analysis.get("inputs", []),
            "outputs": analysis.get("outputs", []),
        }
        self.updated_at = utc_now()


class ConversationStore:
    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root
        self._conversations: Dict[str, Conversation] = {}

    def get_or_create(self, conversation_id: Optional[str]) -> Conversation:
        if conversation_id and conversation_id in self._conversations:
            convo = self._conversations[conversation_id]
            convo.updated_at = utc_now()
            return convo
        new_id = conversation_id or f"conv_{uuid4().hex}"
        convo = Conversation(id=new_id, orchestrator=build_orchestrator(self._repo_root))
        self._conversations[new_id] = convo
        return convo

    def get(self, conversation_id: str) -> Optional[Conversation]:
        return self._conversations.get(conversation_id)
