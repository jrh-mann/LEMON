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

    # Single canonical workflow dict (nodes + edges + inputs + outputs + metadata)
    workflow: Dict[str, Any] = field(default_factory=lambda: {
        "nodes": [],
        "edges": [],
        "inputs": [],
        "outputs": [],
        "tree": {},
        "doubts": []
    })

    # Backward-compatible properties for existing code
    @property
    def workflow_state(self) -> Dict[str, Any]:
        """View of workflow structure (nodes/edges only) for backward compatibility."""
        return {
            "nodes": self.workflow.get("nodes", []),
            "edges": self.workflow.get("edges", [])
        }

    @property
    def workflow_analysis(self) -> Dict[str, Any]:
        """View of workflow metadata (inputs/outputs/tree/doubts) for backward compatibility."""
        return {
            "inputs": self.workflow.get("inputs", []),
            "outputs": self.workflow.get("outputs", []),
            "tree": self.workflow.get("tree", {}),
            "doubts": self.workflow.get("doubts", [])
        }

    def update_workflow_state(self, workflow: Dict[str, Any]) -> None:
        """Update workflow structure (nodes/edges).

        Args:
            workflow: Workflow with nodes and edges
        """
        if not isinstance(workflow, dict):
            return

        # Update nodes and edges in the unified workflow dict
        self.workflow["nodes"] = workflow.get("nodes", [])
        self.workflow["edges"] = workflow.get("edges", [])
        self.updated_at = utc_now()

    def update_workflow_analysis(self, analysis: Dict[str, Any]) -> None:
        """Update workflow metadata (inputs/outputs/tree/doubts).

        Args:
            analysis: Workflow analysis with inputs and outputs
        """
        if not isinstance(analysis, dict):
            return

        # Update inputs/outputs/tree/doubts in the unified workflow dict
        self.workflow["inputs"] = analysis.get("inputs", [])
        self.workflow["outputs"] = analysis.get("outputs", [])
        if "tree" in analysis:
            self.workflow["tree"] = analysis.get("tree", {})
        if "doubts" in analysis:
            self.workflow["doubts"] = analysis.get("doubts", [])
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
