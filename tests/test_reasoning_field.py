"""Tests for reasoning field pipeline — extended thinking captured from subagent
and threaded through to orchestrator system prompt.

Covers:
1. _parse_anthropic_response extracts thinking blocks
2. _parse_anthropic_response returns empty string when no thinking blocks
3. normalize_analysis preserves reasoning key
4. Orchestrator workflow_analysis property includes reasoning
5. Orchestrator workflow_analysis setter stores reasoning
6. build_system_prompt includes reasoning section when non-empty
7. build_system_prompt omits Analysis Context when reasoning is empty
8. Conversation update_workflow_analysis stores reasoning
9. Full pipeline: Conversation -> sync -> Orchestrator -> system prompt
"""

import pytest
from pathlib import Path
from types import SimpleNamespace

from src.backend.llm.anthropic import _parse_anthropic_response
from src.backend.utils.analysis import normalize_analysis
from src.backend.agents.orchestrator import Orchestrator
from src.backend.agents.orchestrator_config import build_system_prompt
from src.backend.api.conversations import Conversation
from src.backend.tools import ToolRegistry


class TestParseAnthropicResponseThinking:
    """Verify _parse_anthropic_response extracts thinking content blocks."""

    def test_extracts_thinking_text(self):
        """Thinking blocks should be concatenated into third return value."""
        message = SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", thinking="Step 1: analyze the nodes."),
                SimpleNamespace(type="thinking", thinking="Step 2: determine variable types."),
                SimpleNamespace(type="text", text="Here is the JSON."),
            ],
            tool_calls=None,
        )

        text, tool_calls, thinking = _parse_anthropic_response(message)

        assert text == "Here is the JSON."
        assert thinking == "Step 1: analyze the nodes.Step 2: determine variable types."
        assert tool_calls == []

    def test_empty_thinking_when_no_thinking_blocks(self):
        """When no thinking blocks exist, thinking should be empty string."""
        message = SimpleNamespace(
            content=[
                SimpleNamespace(type="text", text="Plain response."),
            ],
            tool_calls=None,
        )

        text, tool_calls, thinking = _parse_anthropic_response(message)

        assert text == "Plain response."
        assert thinking == ""

    def test_thinking_from_dict_blocks(self):
        """Thinking extraction should work with dict-style content blocks."""
        # Use SimpleNamespace for message (getattr-compatible) with dict content blocks
        message = SimpleNamespace(
            content=[
                {"type": "thinking", "thinking": "Dict-based thinking."},
                {"type": "text", "text": "Dict-based text."},
            ],
            tool_calls=None,
        )

        text, tool_calls, thinking = _parse_anthropic_response(message)

        assert text == "Dict-based text."
        assert thinking == "Dict-based thinking."


class TestNormalizeAnalysisReasoning:
    """Verify normalize_analysis preserves reasoning key."""

    def test_preserves_reasoning_key(self):
        """reasoning key should survive normalization untouched."""
        analysis = {
            "inputs": [
                {"name": "age", "type": "int", "id": "input_age_int", "description": "Patient age"}
            ],
            "outputs": [],
            "tree": {},
            "doubts": [],
            "reasoning": "The diagram shows a clinical decision tree for age-based screening.",
        }

        result = normalize_analysis(analysis)

        assert result["reasoning"] == "The diagram shows a clinical decision tree for age-based screening."


class TestOrchestratorReasoning:
    """Verify Orchestrator stores and exposes reasoning."""

    def _make_orchestrator(self) -> Orchestrator:
        registry = ToolRegistry()
        return Orchestrator(registry)

    def test_workflow_analysis_includes_reasoning(self):
        """workflow_analysis property should include reasoning field."""
        orch = self._make_orchestrator()
        # Set reasoning in the workflow dict
        orch.workflow["reasoning"] = "Some reasoning text."

        analysis = orch.workflow_analysis

        assert analysis["reasoning"] == "Some reasoning text."

    def test_workflow_analysis_default_reasoning(self):
        """workflow_analysis property should default reasoning to empty string."""
        orch = self._make_orchestrator()

        analysis = orch.workflow_analysis

        assert analysis["reasoning"] == ""

    def test_workflow_analysis_setter_stores_reasoning(self):
        """Setting workflow_analysis with reasoning should persist it."""
        orch = self._make_orchestrator()
        orch.workflow_analysis = {
            "variables": [],
            "outputs": [],
            "tree": {},
            "doubts": [],
            "reasoning": "Setter reasoning.",
        }

        assert orch.workflow["reasoning"] == "Setter reasoning."


class TestBuildSystemPromptReasoning:
    """Verify build_system_prompt handles reasoning injection."""

    def test_includes_reasoning_when_nonempty(self):
        """Non-empty reasoning should produce an 'Analysis Context' section."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=[],
            allow_tools=True,
            reasoning="The blue diamond represents a HbA1c threshold check.",
        )

        assert "## Analysis Context" in prompt
        assert "The blue diamond represents a HbA1c threshold check." in prompt

    def test_omits_reasoning_section_when_empty(self):
        """Empty reasoning should NOT produce an 'Analysis Context' section."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=[],
            allow_tools=True,
            reasoning="",
        )

        assert "## Analysis Context" not in prompt

    def test_omits_reasoning_section_by_default(self):
        """When reasoning param not passed, no Analysis Context section."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=[],
            allow_tools=True,
        )

        assert "## Analysis Context" not in prompt


class TestConversationReasoning:
    """Verify Conversation stores reasoning."""

    def _make_conversation(self) -> Conversation:
        registry = ToolRegistry()
        orch = Orchestrator(registry)
        return Conversation(id="test", orchestrator=orch)

    def test_update_workflow_analysis_stores_reasoning(self):
        """update_workflow_analysis should persist reasoning field."""
        convo = self._make_conversation()
        convo.update_workflow_analysis({
            "variables": [],
            "outputs": [],
            "reasoning": "Conversation-level reasoning.",
        })

        assert convo.workflow["reasoning"] == "Conversation-level reasoning."

    def test_workflow_analysis_property_includes_reasoning(self):
        """workflow_analysis property should expose reasoning."""
        convo = self._make_conversation()
        convo.workflow["reasoning"] = "Property test."

        assert convo.workflow_analysis["reasoning"] == "Property test."

    def test_default_workflow_has_reasoning(self):
        """Default workflow dict should include reasoning key."""
        convo = self._make_conversation()

        assert "reasoning" in convo.workflow
        assert convo.workflow["reasoning"] == ""


class TestFullReasoningPipeline:
    """End-to-end: Conversation -> sync -> Orchestrator -> system prompt."""

    def test_reasoning_flows_through_pipeline(self):
        """reasoning set on Conversation should appear in orchestrator system prompt."""
        registry = ToolRegistry()
        orch = Orchestrator(registry)
        convo = Conversation(id="pipeline_test", orchestrator=orch)

        # 1. Analysis with reasoning arrives
        convo.update_workflow_analysis({
            "variables": [{"id": "input_age_int", "name": "age", "type": "int", "description": ""}],
            "outputs": [],
            "reasoning": "The workflow handles pediatric vs adult dosing.",
        })

        # 2. Sync from conversation -> orchestrator
        orch.sync_workflow_analysis(analysis_provider=lambda: convo.workflow_analysis)

        # 3. Build system prompt with reasoning from orchestrator
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=[],
            allow_tools=True,
            reasoning=orch.workflow_analysis.get("reasoning", ""),
        )

        assert "## Analysis Context" in prompt
        assert "The workflow handles pediatric vs adult dosing." in prompt
