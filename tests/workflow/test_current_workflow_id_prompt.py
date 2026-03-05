"""Tests for workflow name injection into the system prompt.

Verifies that:
1. build_system_prompt includes the workflow name when provided
2. build_system_prompt omits the section when no name is set
3. The workflow name appears early in the prompt (before rules)
"""

from src.backend.agents.system_prompt import build_system_prompt


class TestCurrentWorkflowNameInPrompt:
    """Verify build_system_prompt injects the current workflow name."""

    def test_includes_name_when_provided(self):
        """When current_workflow_name is set, prompt should contain it."""
        prompt = build_system_prompt(
            has_files=[],
            allow_tools=True,
            current_workflow_name="BMI Calculator",
        )

        assert "Active workflow" in prompt
        assert "BMI Calculator" in prompt

    def test_omits_section_when_no_name(self):
        """When current_workflow_name is None, no Active Workflow line."""
        prompt = build_system_prompt(
            has_files=[],
            allow_tools=True,
            current_workflow_name=None,
        )

        assert "Active workflow" not in prompt

    def test_omits_section_by_default(self):
        """When current_workflow_name param not passed, no section appears."""
        prompt = build_system_prompt(
            has_files=[],
            allow_tools=True,
        )

        assert "Active workflow" not in prompt

    def test_name_appears_before_rules(self):
        """The Active Workflow line should appear before the rules section
        so the LLM sees it early in the prompt."""
        prompt = build_system_prompt(
            has_files=[],
            allow_tools=True,
            current_workflow_name="Credit Score Assessment",
        )

        name_pos = prompt.index("Active workflow")
        rules_pos = prompt.index("## Rules")
        assert name_pos < rules_pos, (
            "Active workflow line must appear before rules section"
        )
