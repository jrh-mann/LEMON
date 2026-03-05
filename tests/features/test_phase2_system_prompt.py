"""Tests for the system prompt builder.

Verifies:
1. Signature works with all keyword arguments
2. Image Analysis section is present
3. Core tool documentation sections are preserved
4. Dynamic tail sections (reasoning, guidance, files) are appended
"""


class TestBuildSystemPrompt:
    def test_new_signature_works(self):
        """build_system_prompt accepts the full keyword signature."""
        from src.backend.agents.system_prompt import build_system_prompt

        prompt = build_system_prompt(has_files=None, allow_tools=True)
        assert isinstance(prompt, str)
        assert len(prompt) > 100

    def test_image_analysis_section_present(self):
        """The Image Analysis section should be in the prompt."""
        from src.backend.agents.system_prompt import build_system_prompt

        prompt = build_system_prompt()
        assert "## Image Analysis" in prompt
        assert "update_plan" in prompt
        assert "view_image" in prompt
        assert "ask_question" in prompt

    def test_current_workflow_id_injected(self):
        """When current_workflow_id is given, it appears in the prompt."""
        from src.backend.agents.system_prompt import build_system_prompt

        prompt = build_system_prompt(current_workflow_id="wf_test123")
        assert "wf_test123" in prompt
        assert "Active workflow" in prompt

    def test_current_workflow_id_absent(self):
        """When no current_workflow_id, the active workflow line is omitted."""
        from src.backend.agents.system_prompt import build_system_prompt

        prompt = build_system_prompt()
        assert "Active workflow" not in prompt

    def test_reasoning_context_injected(self):
        """When reasoning is provided, it's appended in an Analysis Context section."""
        from src.backend.agents.system_prompt import build_system_prompt

        prompt = build_system_prompt(reasoning="BMI uses weight/height^2")
        assert "## Analysis Context" in prompt
        assert "BMI uses weight/height^2" in prompt

    def test_reasoning_context_absent(self):
        """When no reasoning, the Analysis Context section is omitted."""
        from src.backend.agents.system_prompt import build_system_prompt

        prompt = build_system_prompt()
        assert "## Analysis Context" not in prompt

    def test_guidance_injected(self):
        """When guidance notes are provided, they appear in an Image Guidance Notes section."""
        from src.backend.agents.system_prompt import build_system_prompt

        notes = [
            {"category": "legend", "text": "Green = pass", "location": "top-right"},
            {"category": "note", "text": "Check HbA1c", "location": "left", "linked_to": "Decision A", "link_type": "arrow"},
        ]
        prompt = build_system_prompt(guidance=notes)
        assert "## Image Guidance Notes" in prompt
        assert "Green = pass" in prompt
        assert "Check HbA1c" in prompt
        # Linked note format: → "Decision A" via arrow
        assert '"Decision A"' in prompt

    def test_guidance_absent(self):
        """When no guidance, the Image Guidance Notes section is omitted."""
        from src.backend.agents.system_prompt import build_system_prompt

        prompt = build_system_prompt()
        assert "## Image Guidance Notes" not in prompt

    def test_session_id_accepted(self):
        """last_session_id parameter is accepted without error (kept for compat)."""
        from src.backend.agents.system_prompt import build_system_prompt

        # Parameter is accepted but no longer injected into prompt text
        prompt = build_system_prompt(last_session_id="sess_abc")
        assert isinstance(prompt, str)
        assert len(prompt) > 100

    def test_core_tool_docs_preserved(self):
        """Core tool documentation sections should still be present."""
        from src.backend.agents.system_prompt import build_system_prompt

        prompt = build_system_prompt()
        # Data model with variables
        assert "## Data Model" in prompt
        assert "### Variables" in prompt
        # Decision conditions
        assert "## Decision Conditions" in prompt
        # Calculation nodes
        assert "## Calculation Nodes" in prompt
        # Subprocess nodes
        assert "## Subprocess Nodes" in prompt
        # Tool selection
        assert "## Tool Selection" in prompt
        # Batch edit
        assert "## Batch Edit" in prompt
        # Tree structure
        assert "## Tree Structure" in prompt

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

    def test_multi_file_classification_prompt(self):
        """When multiple unclassified files are uploaded, prompt asks for classification."""
        from src.backend.agents.system_prompt import build_system_prompt

        files = [
            {"name": "flowchart.png", "purpose": "unclassified"},
            {"name": "legend.pdf", "purpose": "unclassified"},
        ]
        prompt = build_system_prompt(has_files=files)
        assert "flowchart.png" in prompt
        assert "legend.pdf" in prompt
        assert "ask_question" in prompt
