"""Conversation state and orchestrator wiring."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from uuid import uuid4
from pathlib import Path

from ..api.common import utc_now
from ..agents.orchestrator import Orchestrator
from ..agents.orchestrator_factory import build_orchestrator

logger = logging.getLogger(__name__)

# Maximum conversations kept in memory before evicting oldest
_MAX_CONVERSATIONS = 100


@dataclass
class Conversation:
    id: str
    orchestrator: Orchestrator
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    # Single canonical workflow dict (nodes + edges + variables + outputs)
    workflow: Dict[str, Any] = field(default_factory=lambda: {
        "nodes": [],
        "edges": [],
        "variables": [],
        "outputs": [],
        "output_type": "string",
    })

    @property
    def workflow_state(self) -> Dict[str, Any]:
        """View of workflow structure (nodes/edges only) for session_state."""
        return {
            "nodes": self.workflow.get("nodes", []),
            "edges": self.workflow.get("edges", [])
        }

    @property
    def workflow_analysis(self) -> Dict[str, Any]:
        """View of workflow metadata (variables/outputs) for tools."""
        return {
            "variables": self.workflow.get("variables", []),
            "outputs": self.workflow.get("outputs", []),
            "output_type": self.workflow.get("output_type", "string"),
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
        """Update workflow metadata (variables/outputs).

        Args:
            analysis: Workflow analysis with 'variables' and 'outputs' keys.
        """
        if not isinstance(analysis, dict):
            return

        self.workflow["variables"] = analysis.get("variables", [])
        self.workflow["outputs"] = analysis.get("outputs", [])
        self.workflow["output_type"] = analysis.get("output_type", self.workflow.get("output_type", "string"))
        self.updated_at = utc_now()


class ConversationStore:
    def __init__(self, repo_root: Path, conversation_logger: Any = None) -> None:
        self._repo_root = repo_root
        self._conversation_logger = conversation_logger
        self._conversations: Dict[str, Conversation] = {}
        # Lock protects _conversations from concurrent WS thread access
        self._lock = threading.Lock()

    def get_or_create(self, conversation_id: Optional[str]) -> Conversation:
        with self._lock:
            if conversation_id and conversation_id in self._conversations:
                convo = self._conversations[conversation_id]
                convo.updated_at = utc_now()
                return convo
            # Evict oldest conversations when at capacity
            self._evict_if_full()
            new_id = conversation_id or f"conv_{uuid4().hex}"
            convo = Conversation(id=new_id, orchestrator=build_orchestrator(self._repo_root))
            # Reload history from persistent logger when the conversation_id was
            # provided but not found in memory (e.g. after backend restart).
            if conversation_id and self._conversation_logger:
                self._reload_history(convo)
            self._conversations[new_id] = convo
            return convo

    def _reload_history(self, convo: Conversation) -> None:
        """Reload conversation history from ConversationLogger into the orchestrator.

        Called when a known conversation_id is not in memory — typically after
        a backend restart. Reads user/assistant messages and tool calls from
        the persistent SQLite log. Tool calls are attached as tool_calls_meta
        on assistant messages so get_conversation can display them.
        """
        try:
            entries = self._conversation_logger.get_conversation_timeline(
                convo.id,
                entry_types=["user_message", "assistant_response", "tool_call"],
            )
            if not entries:
                return
            history: list[dict] = []
            pending_tool_calls: list[dict] = []
            for entry in entries:
                etype = entry["entry_type"]
                if etype == "tool_call":
                    # Collect tool calls between user message and assistant response
                    tool_args = entry.get("tool_arguments")
                    pending_tool_calls.append({
                        "tool": entry.get("tool_name", ""),
                        "arguments": json.loads(tool_args) if tool_args else {},
                        "success": bool(entry.get("tool_success", 1)),
                    })
                elif etype == "user_message":
                    pending_tool_calls = []
                    content = entry.get("content", "")
                    if content:
                        history.append({"role": "user", "content": content})
                elif etype == "assistant_response":
                    content = entry.get("content", "")
                    # Keep assistant messages with content OR pending tool calls
                    # (ask_question can produce empty-content with tools)
                    if content or pending_tool_calls:
                        msg: dict = {"role": "assistant", "content": content}
                        if pending_tool_calls:
                            msg["tool_calls_meta"] = pending_tool_calls
                            pending_tool_calls = []
                        history.append(msg)
            if history:
                convo.orchestrator.conversation.history = history
                logger.info(
                    "Reloaded %d messages for conversation %s from persistent log",
                    len(history), convo.id,
                )
        except Exception:
            logger.warning(
                "Failed to reload history for conversation %s — starting fresh",
                convo.id, exc_info=True,
            )

    def get(self, conversation_id: str) -> Optional[Conversation]:
        with self._lock:
            return self._conversations.get(conversation_id)

    def _evict_if_full(self) -> None:
        """Remove oldest conversations when store exceeds max capacity.

        Must be called while self._lock is held.
        """
        if len(self._conversations) < _MAX_CONVERSATIONS:
            return
        # Sort by updated_at, evict oldest 10%
        evict_count = max(1, _MAX_CONVERSATIONS // 10)
        sorted_ids = sorted(
            self._conversations,
            key=lambda cid: self._conversations[cid].updated_at,
        )
        for cid in sorted_ids[:evict_count]:
            logger.info("Evicting stale conversation %s", cid)
            del self._conversations[cid]
