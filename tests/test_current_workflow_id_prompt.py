"""Tests for current_workflow_id injection into the system prompt.

Verifies that:
1. build_system_prompt includes the workflow ID when provided
2. build_system_prompt omits the section when no workflow ID is set
3. The workflow ID appears in the correct location (after architecture section)
"""

from src.backend.agents.system_prompt import build_system_prompt


class TestCurrentWorkflowIdInPrompt:
    """Verify build_system_prompt injects the current workflow ID."""

    def test_includes_workflow_id_when_provided(self):
        """When current_workflow_id is set, prompt should contain the ID."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=[],
            allow_tools=True,
            current_workflow_id="wf_abc123",
        )

        assert "### Current Workflow" in prompt
        assert "wf_abc123" in prompt
        assert "Use this ID for all tool calls" in prompt

    def test_omits_section_when_no_workflow_id(self):
        """When current_workflow_id is None, no Current Workflow section."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=[],
            allow_tools=True,
            current_workflow_id=None,
        )

        assert "### Current Workflow" not in prompt

    def test_omits_section_by_default(self):
        """When current_workflow_id param not passed, no section appears."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=[],
            allow_tools=True,
        )

        assert "### Current Workflow" not in prompt

    def test_workflow_id_appears_before_tool_instructions(self):
        """The Current Workflow section should appear before the tool call
        instructions so the LLM sees it early in the prompt."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=[],
            allow_tools=True,
            current_workflow_id="wf_test_456",
        )

        id_pos = prompt.index("### Current Workflow")
        tools_pos = prompt.index("## CRITICAL: When to Call Tools")
        assert id_pos < tools_pos, (
            "Current Workflow section must appear before tool call instructions"
        )
