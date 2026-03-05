"""Tests for current_workflow_id injection into the system prompt.

Verifies that:
1. build_system_prompt includes the workflow ID when provided
2. build_system_prompt omits the section when no workflow ID is set
3. The workflow ID appears early in the prompt (before tool instructions)
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

        assert "Active workflow" in prompt
        assert "wf_abc123" in prompt
        # Implicit binding: tools auto-target the active workflow
        assert "operate on the active workflow automatically" in prompt

    def test_omits_section_when_no_workflow_id(self):
        """When current_workflow_id is None, no Active Workflow line."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=[],
            allow_tools=True,
            current_workflow_id=None,
        )

        assert "Active workflow" not in prompt

    def test_omits_section_by_default(self):
        """When current_workflow_id param not passed, no section appears."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=[],
            allow_tools=True,
        )

        assert "Active workflow" not in prompt

    def test_workflow_id_appears_before_tool_instructions(self):
        """The Active Workflow line should appear before the tool selection
        section so the LLM sees it early in the prompt."""
        prompt = build_system_prompt(
            last_session_id=None,
            has_files=[],
            allow_tools=True,
            current_workflow_id="wf_test_456",
        )

        id_pos = prompt.index("Active workflow")
        tools_pos = prompt.index("## Tool Selection")
        assert id_pos < tools_pos, (
            "Active workflow line must appear before tool selection section"
        )
