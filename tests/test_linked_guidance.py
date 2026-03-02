"""Tests for linked guidance detection — guidance panels that reference specific
flowchart nodes (asterisks, color-coded boxes, arrows) and the formatting /
subflow instructions that flow through to the orchestrator system prompt.

Covers:
1. _extract_guidance normalizes linked_to and link_type fields
2. Standalone items get linked_to=None after normalization
3. Mixed standalone + linked items both returned
4. Empty response returns []
5. build_system_prompt splits standalone vs linked formatting
6. Subagent subworkflows in analysis prompt and result defaulting
7. _process_subworkflows creates workflows and replaces nodes
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.backend.agents.subagent import Subagent
from src.backend.agents.orchestrator_config import build_system_prompt
from src.backend.storage.history import HistoryStore


def _make_subagent() -> Subagent:
    """Create a Subagent with an in-memory history store."""
    history = MagicMock(spec=HistoryStore)
    return Subagent(history)


# ---------------------------------------------------------------------------
# Step 1 tests: _extract_guidance linked field normalization
# ---------------------------------------------------------------------------

class TestLinkedGuidanceExtraction:
    """Verify _extract_guidance handles linked_to and link_type fields."""

    def test_linked_items_preserve_fields(self):
        """Items with linked_to and link_type should keep their values."""
        subagent = _make_subagent()
        llm_response = json.dumps([
            {
                "text": "Treatment Order: 1. Statin 2. Ezetimibe 3. Inclisiran",
                "location": "green box, right side",
                "category": "treatment_detail",
                "linked_to": "Maximally Tolerated Treatment",
                "link_type": "color_group",
            },
        ])

        with patch("src.backend.agents.subagent.call_llm", return_value=llm_response):
            result = subagent._extract_guidance(data_url="data:image/png;base64,abc")

        assert len(result) == 1
        assert result[0]["linked_to"] == "Maximally Tolerated Treatment"
        assert result[0]["link_type"] == "color_group"
        assert result[0]["category"] == "treatment_detail"

    def test_standalone_items_get_null_linked_fields(self):
        """Items without linked_to/link_type get None after normalization."""
        subagent = _make_subagent()
        llm_response = json.dumps([
            {
                "text": "We assume 'Normal' to be 5 or below",
                "location": "yellow sticky, top-right",
                "category": "definition",
            },
        ])

        with patch("src.backend.agents.subagent.call_llm", return_value=llm_response):
            result = subagent._extract_guidance(data_url="data:image/png;base64,abc")

        assert len(result) == 1
        assert result[0]["linked_to"] is None
        assert result[0]["link_type"] is None

    def test_mixed_standalone_and_linked(self):
        """Both standalone and linked items should be returned together."""
        subagent = _make_subagent()
        llm_response = json.dumps([
            {
                "text": "We assume 'Normal' to be 5 or below",
                "location": "yellow sticky, top-right",
                "category": "definition",
            },
            {
                "text": "Step 1: Start statin. Step 2: Add ezetimibe if not at target.",
                "location": "green box, bottom-right",
                "category": "treatment_detail",
                "linked_to": "Optimise Treatment",
                "link_type": "arrow",
            },
            {
                "text": "* See BNF for dosing",
                "location": "footnote, bottom",
                "category": "note",
                "linked_to": "Prescribe Medication",
                "link_type": "asterisk",
            },
        ])

        with patch("src.backend.agents.subagent.call_llm", return_value=llm_response):
            result = subagent._extract_guidance(data_url="data:image/png;base64,abc")

        assert len(result) == 3
        # Standalone item normalized
        assert result[0]["linked_to"] is None
        assert result[0]["link_type"] is None
        # Linked items preserved
        assert result[1]["linked_to"] == "Optimise Treatment"
        assert result[1]["link_type"] == "arrow"
        assert result[2]["linked_to"] == "Prescribe Medication"
        assert result[2]["link_type"] == "asterisk"

    def test_empty_response_returns_empty_list(self):
        """Empty JSON array from LLM should return []."""
        subagent = _make_subagent()

        with patch("src.backend.agents.subagent.call_llm", return_value="[]"):
            result = subagent._extract_guidance(data_url="data:image/png;base64,abc")

        assert result == []


# ---------------------------------------------------------------------------
# Subworkflow prompt & result tests
# ---------------------------------------------------------------------------

class TestSubworkflowPromptAndDefaults:
    """Verify subworkflows are in the prompt schema and default to [] in results."""

    def test_analyze_preserves_subworkflows_from_llm(self):
        """When LLM returns subworkflows, they should be preserved in the result."""
        subagent = _make_subagent()
        subagent.history.list_messages.return_value = []

        # Analysis JSON with a subworkflow entry
        analysis_json = json.dumps({
            "inputs": [
                {"id": "input_ldl_float", "name": "ldl", "type": "float", "description": "LDL level"}
            ],
            "outputs": [{"name": "result", "description": "Result"}],
            "tree": {
                "start": {
                    "id": "start", "type": "start", "label": "Begin",
                    "children": [
                        {"id": "n1", "type": "output", "label": "Done"}
                    ],
                }
            },
            "doubts": [],
            "subworkflows": [
                {
                    "name": "Treatment Protocol",
                    "linked_to_node": "n3",
                    "output_type": "string",
                    "output_variable": "treatment_result",
                    "input_mapping": {"ldl": "ldl_input"},
                    "inputs": [{"id": "input_ldl_float", "name": "ldl", "type": "float"}],
                    "outputs": [{"name": "treatment_result", "description": "Rec"}],
                    "tree": {
                        "start": {
                            "id": "start", "type": "start", "label": "Sub Start",
                            "children": [{"id": "s1", "type": "output", "label": "Sub Done"}],
                        }
                    },
                }
            ],
        })

        with patch("src.backend.agents.subagent.call_llm", return_value=analysis_json), \
             patch("src.backend.agents.subagent.call_llm_stream", return_value=analysis_json), \
             patch("src.backend.agents.subagent.image_to_data_url", return_value="data:image/png;base64,abc"):
            result = subagent.analyze(
                image_path=MagicMock(name="test.png"),
                session_id="test-session",
                stream=lambda x: None,
            )

        assert "subworkflows" in result
        assert len(result["subworkflows"]) == 1
        assert result["subworkflows"][0]["name"] == "Treatment Protocol"

    def test_analyze_defaults_subworkflows_to_empty(self):
        """When LLM omits subworkflows, result should default to []."""
        subagent = _make_subagent()
        subagent.history.list_messages.return_value = []

        # Analysis JSON without subworkflows key
        analysis_json = json.dumps({
            "inputs": [],
            "outputs": [],
            "tree": {
                "start": {
                    "id": "start", "type": "start", "label": "Begin",
                    "children": [{"id": "n1", "type": "output", "label": "Done"}],
                }
            },
            "doubts": [],
        })

        with patch("src.backend.agents.subagent.call_llm", return_value=analysis_json), \
             patch("src.backend.agents.subagent.call_llm_stream", return_value=analysis_json), \
             patch("src.backend.agents.subagent.image_to_data_url", return_value="data:image/png;base64,abc"):
            result = subagent.analyze(
                image_path=MagicMock(name="test.png"),
                session_id="test-session",
                stream=lambda x: None,
            )

        assert "subworkflows" in result
        assert result["subworkflows"] == []

    def test_analyze_multi_defaults_subworkflows_to_empty(self):
        """analyze_multi should also default subworkflows to [] if missing."""
        subagent = _make_subagent()

        analysis_json = json.dumps({
            "inputs": [],
            "outputs": [],
            "tree": {
                "start": {
                    "id": "start", "type": "start", "label": "Begin",
                    "children": [{"id": "n1", "type": "output", "label": "Done"}],
                }
            },
            "doubts": [],
        })

        with patch("src.backend.agents.subagent.call_llm", return_value=analysis_json), \
             patch("src.backend.agents.subagent.call_llm_stream", return_value=analysis_json), \
             patch("src.backend.agents.subagent.file_to_data_url", return_value="data:image/png;base64,abc"):
            result = subagent.analyze_multi(
                classified_files=[{
                    "id": "f1", "name": "test.png", "abs_path": "/tmp/test.png",
                    "file_type": "image", "purpose": "flowchart",
                }],
                session_id="test-multi",
                stream=lambda x: None,
            )

        assert "subworkflows" in result
        assert result["subworkflows"] == []


# ---------------------------------------------------------------------------
# build_system_prompt formatting for linked vs standalone
# ---------------------------------------------------------------------------

class TestBuildSystemPromptLinkedFormatting:
    """Verify build_system_prompt splits standalone and linked guidance."""

    def test_linked_guidance_includes_linked_to_text(self):
        """Linked guidance items should show 'linked to node:' in the prompt."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=[],
            allow_tools=True,
            guidance=[
                {
                    "text": "Treatment protocol steps",
                    "location": "green box",
                    "category": "treatment_detail",
                    "linked_to": "Start Treatment",
                    "link_type": "arrow",
                },
            ],
        )

        assert "linked to node:" in prompt
        assert "Start Treatment" in prompt
        assert "Treatment protocol steps" in prompt

    def test_standalone_only_omits_linked_to_text(self):
        """Standalone-only guidance should not contain 'linked to node:' text."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=[],
            allow_tools=True,
            guidance=[
                {
                    "text": "Normal threshold is 5",
                    "location": "sticky note",
                    "category": "definition",
                    "linked_to": None,
                    "link_type": None,
                },
            ],
        )

        assert "Normal threshold is 5" in prompt
        assert "linked to node:" not in prompt


# ---------------------------------------------------------------------------
# Step 3 tests: ## Subflow Guidance section
# ---------------------------------------------------------------------------

class TestSubflowGuidanceSection:
    """Verify ## Subflow Guidance section is conditionally injected."""

    def test_subflow_section_present_with_linked_guidance(self):
        """When linked guidance exists, ## Subflow Guidance section should appear."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=[],
            allow_tools=True,
            guidance=[
                {
                    "text": "Detailed treatment steps",
                    "location": "green box",
                    "category": "treatment_detail",
                    "linked_to": "Treat Patient",
                    "link_type": "color_group",
                },
            ],
        )

        assert "## Subflow Guidance" in prompt
        assert "create_workflow" in prompt

    def test_subflow_section_absent_without_linked_guidance(self):
        """When no linked guidance exists, ## Subflow Guidance should be absent."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=[],
            allow_tools=True,
            guidance=[
                {
                    "text": "Normal is 5 or below",
                    "location": "sticky",
                    "category": "definition",
                    "linked_to": None,
                    "link_type": None,
                },
            ],
        )

        assert "## Subflow Guidance" not in prompt

    def test_subflow_section_absent_with_no_guidance(self):
        """When guidance is empty, ## Subflow Guidance should be absent."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=[],
            allow_tools=True,
            guidance=[],
        )

        assert "## Subflow Guidance" not in prompt

    def test_subflow_section_absent_when_guidance_none(self):
        """When guidance is None, ## Subflow Guidance should be absent."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=[],
            allow_tools=True,
            guidance=None,
        )

        assert "## Subflow Guidance" not in prompt
