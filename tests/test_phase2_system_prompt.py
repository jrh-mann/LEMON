"""Tests for Phase 2: Rewritten system prompt.

Verifies:
1. New signature works (no last_session_id, reasoning, guidance)
2. Image Analysis section is present
3. Old subagent sections are removed
4. Core tool documentation sections are preserved
"""


class TestBuildSystemPrompt:
    def test_new_signature_works(self):
        """build_system_prompt accepts the new simplified signature."""
        from src.backend.agents.system_prompt import build_system_prompt

        prompt = build_system_prompt(has_files=None, allow_tools=True)
        assert isinstance(prompt, str)
        assert len(prompt) > 100

    def test_image_analysis_section_present(self):
        """The new Image Analysis section should be in the prompt."""
        from src.backend.agents.system_prompt import build_system_prompt

        prompt = build_system_prompt()
        assert "## Image Analysis (CRITICAL)" in prompt
        assert "update_plan" in prompt
        assert "view_image" in prompt
        assert "add_image_question" in prompt

    def test_old_subagent_sections_removed(self):
        """Old subagent-specific content should NOT be in the prompt."""
        from src.backend.agents.system_prompt import build_system_prompt

        prompt = build_system_prompt()
        assert "analyze_workflow" not in prompt
        assert "publish_latest_analysis" not in prompt
        assert "session_id" not in prompt
        assert "## Post-Analysis Workflow" not in prompt
        assert "## Analysis Context" not in prompt
        assert "## Image Guidance Notes" not in prompt

    def test_core_tool_docs_preserved(self):
        """Core tool documentation sections should still be present."""
        from src.backend.agents.system_prompt import build_system_prompt

        prompt = build_system_prompt()
        # Workflow variables section
        assert "## Workflow Variables (CRITICAL)" in prompt
        # Decision conditions
        assert "## Decision Node Conditions (CRITICAL)" in prompt
        # Calculation nodes
        assert "## Calculation Nodes (Mathematical Operations)" in prompt
        # Subprocess nodes
        assert "## Subprocess Nodes (Subflows)" in prompt
        # Node branching rules
        assert "## Node Branching Rules (CRITICAL)" in prompt
        # Batch edit
        assert "## When to Use batch_edit_workflow vs Single Tools" in prompt
        # Structure & Balancing
        assert "## Structure & Balancing (CRITICAL)" in prompt

    def test_tools_disabled_appended(self):
        """When allow_tools=False, the tools-disabled message should appear."""
        from src.backend.agents.system_prompt import build_system_prompt

        prompt = build_system_prompt(allow_tools=False)
        assert "Tools are disabled" in prompt

    def test_tools_enabled_no_disabled_msg(self):
        """When allow_tools=True, the tools-disabled message should NOT appear."""
        from src.backend.agents.system_prompt import build_system_prompt

        prompt = build_system_prompt(allow_tools=True)
        assert "Tools are disabled" not in prompt
