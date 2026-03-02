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
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.backend.agents.subagent import Subagent, _format_guidance
from src.backend.agents.system_prompt import build_system_prompt
from src.backend.storage.history import HistoryStore
from src.backend.tools.workflow_analysis.analyze import AnalyzeWorkflowTool


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
# _process_subworkflows tests
# ---------------------------------------------------------------------------

def _make_valid_subworkflow(linked_to_node="n3"):
    """Helper: returns a valid subworkflow definition dict."""
    return {
        "name": "Treatment Protocol",
        "linked_to_node": linked_to_node,
        "output_type": "string",
        "output_variable": "treatment_result",
        "input_mapping": {"ldl": "ldl_input"},
        "inputs": [
            {"id": "input_ldl_float", "name": "ldl", "type": "float", "description": "LDL level"}
        ],
        "outputs": [{"name": "treatment_result", "description": "Treatment rec"}],
        "tree": {
            "start": {
                "id": "start", "type": "start", "label": "Sub Start",
                "children": [{"id": "s1", "type": "output", "label": "Sub Done"}],
            }
        },
    }


def _make_response_with_action_node(node_id="n3"):
    """Helper: returns a standard response dict with an action node in tree and flowchart."""
    return {
        "session_id": "test-session",
        "analysis": {
            "variables": [
                {"id": "input_ldl_float", "name": "ldl", "type": "float", "source": "input"}
            ],
            "outputs": [{"name": "result", "description": "Result"}],
            "tree": {
                "start": {
                    "id": "start", "type": "start", "label": "Begin",
                    "children": [
                        {
                            "id": node_id, "type": "action", "label": "Treat Patient",
                            "children": [
                                {"id": "n4", "type": "output", "label": "Done"}
                            ],
                        }
                    ],
                }
            },
            "doubts": [],
            "guidance": [],
            "subworkflows": [_make_valid_subworkflow(node_id)],
        },
        "flowchart": {
            "nodes": [
                {"id": "start", "type": "start", "label": "Begin", "x": 0, "y": 0},
                {"id": node_id, "type": "process", "label": "Treat Patient", "x": 0, "y": 100},
                {"id": "n4", "type": "output", "label": "Done", "x": 0, "y": 200},
            ],
            "edges": [
                {"id": "start->n3", "from": "start", "to": node_id, "label": ""},
                {"id": "n3->n4", "from": node_id, "to": "n4", "label": ""},
            ],
        },
    }


class TestProcessSubworkflows:
    """Verify _process_subworkflows creates workflows and replaces nodes."""

    def _make_tool(self):
        """Create AnalyzeWorkflowTool with mocked data_dir."""
        with patch.object(AnalyzeWorkflowTool, "__init__", lambda self, *a, **kw: None):
            tool = AnalyzeWorkflowTool.__new__(AnalyzeWorkflowTool)
            tool._logger = MagicMock()
            tool.repo_root = Path("/tmp")
            tool.data_dir = Path("/tmp")
            return tool

    def test_valid_subworkflow_creates_workflow_and_replaces_node(self):
        """A valid subworkflow should create a DB workflow and replace the action node."""
        tool = self._make_tool()
        mock_store = MagicMock()
        session_state = {"workflow_store": mock_store, "user_id": "user1"}
        response = _make_response_with_action_node("n3")

        result = tool._process_subworkflows(response, session_state)

        # Workflow created in DB
        mock_store.create_workflow.assert_called_once()
        call_kwargs = mock_store.create_workflow.call_args
        assert call_kwargs[1]["name"] == "Treatment Protocol" or call_kwargs.kwargs.get("name") == "Treatment Protocol"

        # Node replaced in flowchart
        fc_node = next(n for n in result["flowchart"]["nodes"] if n["id"] == "n3")
        assert fc_node["type"] == "subprocess"
        assert "subworkflow_id" in fc_node
        assert fc_node["input_mapping"] == {"ldl": "ldl_input"}
        assert fc_node["output_variable"] == "treatment_result"

        # Node replaced in tree
        tree_child = result["analysis"]["tree"]["start"]["children"][0]
        assert tree_child["id"] == "n3"
        assert tree_child["type"] == "subprocess"
        assert "subworkflow_id" in tree_child

        # Output variable registered
        var_names = [v["name"] for v in result["analysis"]["variables"]]
        assert "treatment_result" in var_names
        sub_var = next(v for v in result["analysis"]["variables"] if v["name"] == "treatment_result")
        assert sub_var["source"] == "subprocess"
        assert sub_var["source_node_id"] == "n3"

        # created_subworkflows tracked
        assert "created_subworkflows" in result
        assert len(result["created_subworkflows"]) == 1

    def test_empty_subworkflows_no_changes(self):
        """Empty subworkflows array should not modify the response."""
        tool = self._make_tool()
        response = {
            "analysis": {"variables": [], "tree": {}, "subworkflows": []},
            "flowchart": {"nodes": [], "edges": []},
        }
        session_state = {"workflow_store": MagicMock(), "user_id": "u1"}

        result = tool._process_subworkflows(response, session_state)

        assert "created_subworkflows" not in result

    def test_invalid_sub_tree_skipped(self):
        """A subworkflow with invalid tree should be skipped, main analysis unchanged."""
        tool = self._make_tool()
        mock_store = MagicMock()
        session_state = {"workflow_store": mock_store, "user_id": "user1"}
        response = _make_response_with_action_node("n3")
        # Break the sub-tree: missing start node
        response["analysis"]["subworkflows"][0]["tree"] = {"invalid": True}

        result = tool._process_subworkflows(response, session_state)

        # Workflow NOT created
        mock_store.create_workflow.assert_not_called()
        # Node still action in flowchart
        fc_node = next(n for n in result["flowchart"]["nodes"] if n["id"] == "n3")
        assert fc_node["type"] == "process"

    def test_linked_to_node_not_found_skipped(self):
        """When linked_to_node doesn't match any node, subworkflow still created but no replacement."""
        tool = self._make_tool()
        mock_store = MagicMock()
        session_state = {"workflow_store": mock_store, "user_id": "user1"}
        response = _make_response_with_action_node("n3")
        # Change linked_to_node to a non-existent ID
        response["analysis"]["subworkflows"][0]["linked_to_node"] = "nonexistent"

        result = tool._process_subworkflows(response, session_state)

        # Workflow was still created (it's valid)
        mock_store.create_workflow.assert_called_once()
        # But n3 is still "process" in flowchart (not replaced)
        fc_node = next(n for n in result["flowchart"]["nodes"] if n["id"] == "n3")
        assert fc_node["type"] == "process"
        # Warning logged
        tool._logger.warning.assert_called()

    def test_no_workflow_store_skips_gracefully(self):
        """No workflow_store in session_state should skip all subworkflows."""
        tool = self._make_tool()
        response = _make_response_with_action_node("n3")
        session_state = {"user_id": "user1"}  # No workflow_store

        result = tool._process_subworkflows(response, session_state)

        # No modifications
        fc_node = next(n for n in result["flowchart"]["nodes"] if n["id"] == "n3")
        assert fc_node["type"] == "process"

    def test_no_user_id_skips_gracefully(self):
        """No user_id in session_state should skip all subworkflows."""
        tool = self._make_tool()
        response = _make_response_with_action_node("n3")
        session_state = {"workflow_store": MagicMock()}  # No user_id

        result = tool._process_subworkflows(response, session_state)

        fc_node = next(n for n in result["flowchart"]["nodes"] if n["id"] == "n3")
        assert fc_node["type"] == "process"

    def test_missing_required_fields_skipped(self):
        """Subworkflow entries missing required fields should be skipped."""
        tool = self._make_tool()
        mock_store = MagicMock()
        session_state = {"workflow_store": mock_store, "user_id": "user1"}
        response = _make_response_with_action_node("n3")
        # Remove required field
        del response["analysis"]["subworkflows"][0]["output_type"]

        result = tool._process_subworkflows(response, session_state)

        mock_store.create_workflow.assert_not_called()

    def test_db_creation_failure_skipped(self):
        """If DB creation fails, that subworkflow is skipped but response still returned."""
        tool = self._make_tool()
        mock_store = MagicMock()
        mock_store.create_workflow.side_effect = RuntimeError("DB error")
        session_state = {"workflow_store": mock_store, "user_id": "user1"}
        response = _make_response_with_action_node("n3")

        result = tool._process_subworkflows(response, session_state)

        # Node NOT replaced (creation failed)
        fc_node = next(n for n in result["flowchart"]["nodes"] if n["id"] == "n3")
        assert fc_node["type"] == "process"
        # Error logged
        tool._logger.error.assert_called()


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

    def test_linked_guidance_includes_subworkflow_hint(self):
        """Linked guidance in subagent _format_guidance should include a subworkflow hint."""
        result = _format_guidance(
            [
                {
                    "text": "Treatment protocol steps",
                    "location": "green box",
                    "category": "treatment_detail",
                    "linked_to": "Start Treatment",
                    "link_type": "arrow",
                },
            ],
            header="Side Information Found in Image",
        )

        assert "MUST create a subworkflow" in result

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

    def test_standalone_only_omits_subworkflow_hint(self):
        """Standalone-only guidance in subagent _format_guidance omits subworkflow hint."""
        result = _format_guidance(
            [
                {
                    "text": "Normal threshold is 5",
                    "location": "sticky note",
                    "category": "definition",
                    "linked_to": None,
                    "link_type": None,
                },
            ],
            header="Side Information Found in Image",
        )

        assert "MUST create a subworkflow" not in result


# ---------------------------------------------------------------------------
# Subflow Guidance section removed — subagent handles subworkflows now
# ---------------------------------------------------------------------------

class TestSubflowGuidanceSectionRemoved:
    """Verify ## Subflow Guidance section is no longer in the orchestrator prompt.

    Subworkflow creation is now handled by the subagent + _process_subworkflows,
    so the orchestrator prompt should NOT contain ## Subflow Guidance.
    """

    def test_subflow_section_absent_with_linked_guidance(self):
        """Even with linked guidance, ## Subflow Guidance should be absent."""
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

        assert "## Subflow Guidance" not in prompt
        # Linked guidance text is still shown for context
        assert "linked to node:" in prompt
        assert "Treat Patient" in prompt

    def test_subflow_section_absent_without_linked_guidance(self):
        """Without linked guidance, ## Subflow Guidance should be absent."""
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
