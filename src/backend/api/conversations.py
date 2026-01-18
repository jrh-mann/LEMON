"""Conversation state and orchestrator wiring."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional
from uuid import uuid4
from pathlib import Path

from .common import utc_now
from ..orchestrator import Orchestrator
from ..tools import AnalyzeWorkflowTool, PublishLatestAnalysisTool, ToolRegistry


def build_orchestrator(repo_root: Path) -> Orchestrator:
    registry = ToolRegistry()
    registry.register(AnalyzeWorkflowTool(repo_root))
    registry.register(PublishLatestAnalysisTool(repo_root))
    return Orchestrator(registry)


@dataclass
class Conversation:
    id: str
    orchestrator: Orchestrator
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


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
