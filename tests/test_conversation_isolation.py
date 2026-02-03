"""Tests for conversation isolation — each conversation_id gets independent state.

Verifies that the ConversationStore creates separate orchestrator instances
and workflow state per conversation_id, so different workflow tabs don't
share chat history or workflow data.
"""

import pytest
from pathlib import Path
from src.backend.api.conversations import ConversationStore, Conversation


class TestConversationIsolation:
    """Verify that separate conversation_ids produce independent state."""

    def setup_method(self):
        self.store = ConversationStore(repo_root=Path("."))

    def test_different_ids_create_separate_conversations(self):
        """Two conversation_ids should produce distinct Conversation objects."""
        convo_a = self.store.get_or_create("convo_a")
        convo_b = self.store.get_or_create("convo_b")

        assert convo_a.id == "convo_a"
        assert convo_b.id == "convo_b"
        assert convo_a is not convo_b

    def test_same_id_returns_same_conversation(self):
        """Requesting the same conversation_id should return the same object."""
        convo_1 = self.store.get_or_create("convo_x")
        convo_2 = self.store.get_or_create("convo_x")

        assert convo_1 is convo_2

    def test_separate_orchestrators_per_conversation(self):
        """Each conversation should have its own orchestrator instance."""
        convo_a = self.store.get_or_create("convo_a")
        convo_b = self.store.get_or_create("convo_b")

        assert convo_a.orchestrator is not convo_b.orchestrator

    def test_workflow_state_isolated_between_conversations(self):
        """Modifying workflow in conversation A should not affect conversation B."""
        convo_a = self.store.get_or_create("convo_a")
        convo_b = self.store.get_or_create("convo_b")

        # Add nodes to conversation A
        convo_a.update_workflow_state({
            "nodes": [{"id": "n1", "type": "start", "label": "Begin", "x": 0, "y": 0}],
            "edges": [],
        })

        # Conversation B should still have empty workflow
        assert convo_b.workflow["nodes"] == []
        assert convo_b.workflow["edges"] == []

        # Conversation A should have the node
        assert len(convo_a.workflow["nodes"]) == 1
        assert convo_a.workflow["nodes"][0]["id"] == "n1"

    def test_workflow_analysis_isolated_between_conversations(self):
        """Modifying analysis in conversation A should not affect conversation B."""
        convo_a = self.store.get_or_create("convo_a")
        convo_b = self.store.get_or_create("convo_b")

        # Add variables to conversation A's analysis
        convo_a.update_workflow_analysis({
            "variables": [{"id": "var_age_int", "name": "Age", "type": "int", "source": "input"}],
            "outputs": [{"type": "string"}],
        })

        # Conversation B should have empty analysis
        assert convo_b.workflow["inputs"] == []
        assert convo_b.workflow["outputs"] == []

        # Conversation A should have the variable
        assert len(convo_a.workflow["inputs"]) == 1
        assert convo_a.workflow["inputs"][0]["id"] == "var_age_int"

    def test_orchestrator_message_history_isolated(self):
        """Messages added to one orchestrator should not appear in another."""
        convo_a = self.store.get_or_create("convo_a")
        convo_b = self.store.get_or_create("convo_b")

        # Add a message to conversation A's orchestrator history
        convo_a.orchestrator.history.append({
            "role": "user",
            "content": "Build me a workflow for age checking",
        })

        # Conversation B's orchestrator should have no history
        assert len(convo_b.orchestrator.history) == 0

        # Conversation A should have the message
        assert len(convo_a.orchestrator.history) == 1

    def test_null_id_generates_unique_conversations(self):
        """Passing None as conversation_id should create distinct conversations each time."""
        convo_1 = self.store.get_or_create(None)
        convo_2 = self.store.get_or_create(None)

        assert convo_1.id != convo_2.id
        assert convo_1 is not convo_2

    def test_get_returns_none_for_unknown_id(self):
        """get() should return None for a conversation_id that doesn't exist."""
        result = self.store.get("nonexistent")
        assert result is None

    def test_get_returns_existing_conversation(self):
        """get() should return the conversation if it exists."""
        created = self.store.get_or_create("convo_z")
        fetched = self.store.get("convo_z")

        assert fetched is created
