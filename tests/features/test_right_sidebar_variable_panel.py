from pathlib import Path


def test_right_sidebar_shows_variable_panel_without_existing_analysis():
    content = Path("src/frontend/src/components/RightSidebar.tsx").read_text(encoding="utf-8")
    assert "const effectiveAnalysis: WorkflowAnalysis = currentAnalysis ??" in content
    assert ") : (" in content
    assert "currentAnalysis ? (" not in content


def test_right_sidebar_can_save_new_variables_from_empty_analysis():
    content = Path("src/frontend/src/components/RightSidebar.tsx").read_text(encoding="utf-8")
    assert "...effectiveAnalysis" in content
    assert "if (!currentAnalysis) return" not in content
