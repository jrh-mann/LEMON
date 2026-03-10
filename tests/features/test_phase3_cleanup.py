"""Phase 3 tests: verify subagent pipeline is fully removed.

Checks that:
- Deleted modules cannot be imported
- No stale references remain in active code
- Remaining modules still import correctly
"""

from __future__ import annotations

import importlib

import pytest


class TestDeletedModulesGone:
    """Deleted subagent-related modules must not be importable."""

    @pytest.mark.parametrize("module", [
        "src.backend.agents.subagent",
        "src.backend.tools.workflow_analysis.analyze",
        "src.backend.tools.workflow_analysis.publish",
        "src.backend.utils.analysis",
        "src.backend.storage.history",
        "src.backend.validation.tree_validator",
        "src.backend.validation.retry_harness",
        "src.backend.mcp_bridge",
        "src.backend.mcp_bridge.server",
        "src.backend.mcp_bridge.client",
    ])
    def test_deleted_module_not_importable(self, module: str):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(module)


class TestRemainingModulesImport:
    """Active modules must still import without errors."""

    @pytest.mark.parametrize("module", [
        "src.backend.agents.orchestrator",
        "src.backend.agents.system_prompt",
        "src.backend.tools.schema_gen",
        "src.backend.api.conversations",
        "src.backend.api.ws_chat",
        "src.backend.api.response_utils",
        "src.backend.api.tool_summaries",
        "src.backend.tools",
        "src.backend.tools.workflow_analysis",
        "src.backend.validation",
        "src.backend.utils.flowchart",
        "src.backend.utils.logging",
    ])
    def test_module_imports(self, module: str):
        mod = importlib.import_module(module)
        assert mod is not None


class TestNoStaleReferences:
    """Verify no stale references to deleted concepts in key modules."""

    def test_tool_summaries_no_analyze(self):
        from src.backend.api.tool_summaries import TOOL_STATUS_MESSAGES, TOOL_FAILURE_MESSAGES
        assert "analyze_workflow" not in TOOL_STATUS_MESSAGES
        assert "publish_latest_analysis" not in TOOL_STATUS_MESSAGES
        assert "analyze_workflow" not in TOOL_FAILURE_MESSAGES
        assert "publish_latest_analysis" not in TOOL_FAILURE_MESSAGES

    def test_tool_summaries_has_new_tools(self):
        from src.backend.api.tool_summaries import TOOL_STATUS_MESSAGES, TOOL_FAILURE_MESSAGES
        assert "view_image" in TOOL_STATUS_MESSAGES
        assert "update_plan" in TOOL_STATUS_MESSAGES
        assert "view_image" in TOOL_FAILURE_MESSAGES
        assert "update_plan" in TOOL_FAILURE_MESSAGES

    def test_validation_no_tree_validator(self):
        import src.backend.validation as val
        assert not hasattr(val, "TreeValidator")
        assert not hasattr(val, "validate_and_retry")

    def test_tools_export_new_not_old(self):
        from src.backend.tools import __all__ as tools_all
        assert "ViewImageTool" in tools_all
        assert "UpdatePlanTool" in tools_all
        assert "AnalyzeWorkflowTool" not in tools_all
        assert "PublishLatestAnalysisTool" not in tools_all
