"""Tests for guidance extraction pipeline — side information (sticky notes,
annotations, legends) extracted from workflow images and threaded through
to the orchestrator system prompt.

Covers:
1. _extract_guidance returns list of dicts from valid LLM response
2. _extract_guidance returns [] on invalid JSON (non-blocking)
3. _extract_guidance returns [] on LLM exception (non-blocking)
4. normalize_analysis preserves guidance key
5. Orchestrator workflow_analysis property includes guidance
6. Orchestrator workflow_analysis setter stores guidance
7. build_system_prompt includes guidance section when non-empty
8. build_system_prompt omits section when guidance is empty/None
9. Conversation update_workflow_analysis stores guidance
10. Full pipeline: guidance set on Conversation -> sync -> Orchestrator -> system prompt
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.backend.agents.subagent import Subagent
from src.backend.utils.analysis import normalize_analysis
from src.backend.agents.orchestrator import Orchestrator
from src.backend.agents.orchestrator_config import build_system_prompt
from src.backend.api.conversations import Conversation
from src.backend.tools import ToolRegistry
from src.backend.storage.history import HistoryStore


def _make_subagent() -> Subagent:
    """Create a Subagent with an in-memory history store."""
    history = MagicMock(spec=HistoryStore)
    return Subagent(history)


class TestExtractGuidance:
    """Verify _extract_guidance parses LLM responses correctly."""

    def test_returns_list_from_valid_response(self):
        """Valid JSON array from LLM should be parsed into guidance items."""
        subagent = _make_subagent()
        llm_response = json.dumps([
            {
                "text": "HbA1c threshold is 7.5%",
                "location": "sticky note, top-right",
                "category": "definition",
            },
            {
                "text": "BMI >= 30 is obese",
                "location": "margin note, bottom",
                "category": "constraint",
            },
        ])

        with patch("src.backend.agents.subagent.call_llm", return_value=llm_response):
            result = subagent._extract_guidance(data_url="data:image/png;base64,abc")

        assert len(result) == 2
        assert result[0]["text"] == "HbA1c threshold is 7.5%"
        assert result[0]["category"] == "definition"
        assert result[1]["text"] == "BMI >= 30 is obese"
        assert result[1]["location"] == "margin note, bottom"

    def test_returns_empty_on_invalid_json(self):
        """Invalid JSON from LLM should return [] without raising."""
        subagent = _make_subagent()

        with patch("src.backend.agents.subagent.call_llm", return_value="not valid json at all"):
            result = subagent._extract_guidance(data_url="data:image/png;base64,abc")

        assert result == []

    def test_returns_empty_on_llm_exception(self):
        """LLM exception should return [] without raising (non-blocking)."""
        subagent = _make_subagent()

        with patch("src.backend.agents.subagent.call_llm", side_effect=RuntimeError("API error")):
            result = subagent._extract_guidance(data_url="data:image/png;base64,abc")

        assert result == []

    def test_handles_code_fenced_response(self):
        """LLM response wrapped in code fences should be parsed correctly."""
        subagent = _make_subagent()
        inner = json.dumps([{"text": "Legend: blue = approved", "location": "bottom-left", "category": "legend"}])
        llm_response = f"```json\n{inner}\n```"

        with patch("src.backend.agents.subagent.call_llm", return_value=llm_response):
            result = subagent._extract_guidance(data_url="data:image/png;base64,abc")

        assert len(result) == 1
        assert result[0]["text"] == "Legend: blue = approved"

    def test_returns_empty_on_non_list_json(self):
        """JSON object (not array) from LLM should return []."""
        subagent = _make_subagent()

        with patch("src.backend.agents.subagent.call_llm", return_value='{"text": "not an array"}'):
            result = subagent._extract_guidance(data_url="data:image/png;base64,abc")

        assert result == []

    def test_filters_items_without_text_key(self):
        """Items missing the 'text' key should be filtered out."""
        subagent = _make_subagent()
        llm_response = json.dumps([
            {"text": "Valid item", "location": "top", "category": "note"},
            {"location": "bottom", "category": "note"},  # Missing 'text'
        ])

        with patch("src.backend.agents.subagent.call_llm", return_value=llm_response):
            result = subagent._extract_guidance(data_url="data:image/png;base64,abc")

        assert len(result) == 1
        assert result[0]["text"] == "Valid item"


class TestNormalizeAnalysisGuidance:
    """Verify normalize_analysis preserves guidance key."""

    def test_preserves_guidance_key(self):
        """guidance key should survive normalization untouched."""
        analysis = {
            "inputs": [
                {"name": "age", "type": "int", "id": "input_age_int", "description": "Patient age"}
            ],
            "outputs": [],
            "tree": {},
            "doubts": [],
            "guidance": [
                {"text": "HbA1c threshold is 7.5%", "location": "top-right", "category": "definition"}
            ],
        }

        result = normalize_analysis(analysis)

        assert result["guidance"] == [
            {"text": "HbA1c threshold is 7.5%", "location": "top-right", "category": "definition"}
        ]


class TestOrchestratorGuidance:
    """Verify Orchestrator stores and exposes guidance."""

    def _make_orchestrator(self) -> Orchestrator:
        registry = ToolRegistry()
        return Orchestrator(registry)

    def test_workflow_analysis_includes_guidance(self):
        """workflow_analysis property should include guidance field."""
        orch = self._make_orchestrator()
        orch.workflow["guidance"] = [
            {"text": "Note A", "location": "top", "category": "note"}
        ]

        analysis = orch.workflow_analysis

        assert len(analysis["guidance"]) == 1
        assert analysis["guidance"][0]["text"] == "Note A"

    def test_workflow_analysis_default_guidance(self):
        """workflow_analysis property should default guidance to empty list."""
        orch = self._make_orchestrator()

        analysis = orch.workflow_analysis

        assert analysis["guidance"] == []

    def test_workflow_analysis_setter_stores_guidance(self):
        """Setting workflow_analysis with guidance should persist it."""
        orch = self._make_orchestrator()
        orch.workflow_analysis = {
            "variables": [],
            "outputs": [],
            "tree": {},
            "doubts": [],
            "reasoning": "",
            "guidance": [
                {"text": "Setter guidance", "location": "left", "category": "clarification"}
            ],
        }

        assert len(orch.workflow["guidance"]) == 1
        assert orch.workflow["guidance"][0]["text"] == "Setter guidance"


class TestBuildSystemPromptGuidance:
    """Verify build_system_prompt handles guidance injection."""

    def test_includes_guidance_when_nonempty(self):
        """Non-empty guidance should produce an 'Image Guidance Notes' section."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_image=False,
            allow_tools=True,
            guidance=[
                {"text": "HbA1c threshold is 7.5%", "location": "top-right", "category": "definition"},
                {"text": "BMI >= 30 is obese", "location": "bottom", "category": "constraint"},
            ],
        )

        assert "## Image Guidance Notes" in prompt
        assert "HbA1c threshold is 7.5%" in prompt
        assert "BMI >= 30 is obese" in prompt
        assert "[definition]" in prompt
        assert "[constraint]" in prompt

    def test_omits_guidance_section_when_empty(self):
        """Empty guidance list should NOT produce an 'Image Guidance Notes' section."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_image=False,
            allow_tools=True,
            guidance=[],
        )

        assert "## Image Guidance Notes" not in prompt

    def test_omits_guidance_section_when_none(self):
        """None guidance should NOT produce an 'Image Guidance Notes' section."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_image=False,
            allow_tools=True,
            guidance=None,
        )

        assert "## Image Guidance Notes" not in prompt

    def test_omits_guidance_section_by_default(self):
        """When guidance param not passed, no Image Guidance Notes section."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_image=False,
            allow_tools=True,
        )

        assert "## Image Guidance Notes" not in prompt


class TestConversationGuidance:
    """Verify Conversation stores guidance."""

    def _make_conversation(self) -> Conversation:
        registry = ToolRegistry()
        orch = Orchestrator(registry)
        return Conversation(id="test", orchestrator=orch)

    def test_update_workflow_analysis_stores_guidance(self):
        """update_workflow_analysis should persist guidance field."""
        convo = self._make_conversation()
        convo.update_workflow_analysis({
            "variables": [],
            "outputs": [],
            "guidance": [
                {"text": "Convo guidance", "location": "right", "category": "note"}
            ],
        })

        assert len(convo.workflow["guidance"]) == 1
        assert convo.workflow["guidance"][0]["text"] == "Convo guidance"

    def test_workflow_analysis_property_includes_guidance(self):
        """workflow_analysis property should expose guidance."""
        convo = self._make_conversation()
        convo.workflow["guidance"] = [
            {"text": "Property test", "location": "top", "category": "clarification"}
        ]

        assert len(convo.workflow_analysis["guidance"]) == 1
        assert convo.workflow_analysis["guidance"][0]["text"] == "Property test"

    def test_default_workflow_has_guidance(self):
        """Default workflow dict should include guidance key."""
        convo = self._make_conversation()

        assert "guidance" in convo.workflow
        assert convo.workflow["guidance"] == []


class TestFullGuidancePipeline:
    """End-to-end: Conversation -> sync -> Orchestrator -> system prompt."""

    def test_guidance_flows_through_pipeline(self):
        """guidance set on Conversation should appear in orchestrator system prompt."""
        registry = ToolRegistry()
        orch = Orchestrator(registry)
        convo = Conversation(id="pipeline_test", orchestrator=orch)

        # 1. Analysis with guidance arrives
        convo.update_workflow_analysis({
            "variables": [{"id": "input_age_int", "name": "age", "type": "int", "description": ""}],
            "outputs": [],
            "guidance": [
                {"text": "HbA1c threshold is 7.5%", "location": "top-right", "category": "definition"},
                {"text": "BMI >= 30 is obese", "location": "bottom margin", "category": "constraint"},
            ],
        })

        # 2. Sync from conversation -> orchestrator
        orch.sync_workflow_analysis(analysis_provider=lambda: convo.workflow_analysis)

        # 3. Build system prompt with guidance from orchestrator
        prompt = build_system_prompt(
            last_session_id=None,
            has_image=False,
            allow_tools=True,
            reasoning=orch.workflow_analysis.get("reasoning", ""),
            guidance=orch.workflow_analysis.get("guidance", []),
        )

        assert "## Image Guidance Notes" in prompt
        assert "HbA1c threshold is 7.5%" in prompt
        assert "BMI >= 30 is obese" in prompt
