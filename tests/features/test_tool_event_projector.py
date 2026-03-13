"""Tests for ToolEventProjector — tool lifecycle → SSE event translation.

Covers:
1. tool_start records entry and emits progress
2. tool_complete records result and snapshots workflow
3. tool_batch_complete flushes summary and emits "thinking"
4. Cancelled tasks skip SSE emissions but still record entries
5. WORKFLOW_EDIT_TOOLS emit workflow_update + workflow_state_updated
6. WORKFLOW_INPUT_TOOLS emit analysis_updated
7. ask_question emits pending_question
8. save_workflow_to_library emits workflow_saved
9. flush_tool_summary delegates to stream_chunk
"""

from unittest.mock import MagicMock, call

from src.backend.api.tool_event_projector import ToolEventProjector


def _make_projector(
    *,
    is_cancelled: bool = False,
    has_convo: bool = True,
    workflow_analysis: dict | None = None,
) -> tuple[ToolEventProjector, dict[str, MagicMock]]:
    """Build a projector with mock callables and return (projector, mocks_dict)."""
    mocks = {
        "publish": MagicMock(),
        "publish_workflow_state": MagicMock(),
        "emit_progress": MagicMock(),
        "stream_chunk": MagicMock(),
        "is_cancelled": MagicMock(return_value=is_cancelled),
        "get_workflow_state_payload": MagicMock(return_value={
            "workflow_id": "wf-1",
            "workflow": {"nodes": []},
            "analysis": workflow_analysis or {"variables": [], "outputs": []},
            "task_id": "t1",
        } if has_convo else None),
        "get_workflow_analysis": MagicMock(return_value=workflow_analysis or {"variables": [], "outputs": []}),
        "conversation_logger": MagicMock(),
        "get_convo_id": MagicMock(return_value="conv-1" if has_convo else None),
        "get_current_workflow": MagicMock(return_value={"nodes": []} if has_convo else None),
    }

    projector = ToolEventProjector(
        task_id="t1",
        publish=mocks["publish"],
        publish_workflow_state=mocks["publish_workflow_state"],
        emit_progress=mocks["emit_progress"],
        stream_chunk=mocks["stream_chunk"],
        is_cancelled=mocks["is_cancelled"],
        get_workflow_state_payload=mocks["get_workflow_state_payload"],
        get_workflow_analysis=mocks["get_workflow_analysis"],
        conversation_logger=mocks["conversation_logger"],
        get_convo_id=mocks["get_convo_id"],
        get_current_workflow=mocks["get_current_workflow"],
    )
    return projector, mocks


# ── tool_start ───────────────────────────────────────────

class TestToolStart:
    def test_records_entry(self):
        proj, _ = _make_projector()
        proj.on_tool_event("tool_start", "add_node", {"label": "A"}, None)
        assert len(proj.executed_tools) == 1
        assert proj.executed_tools[0]["tool"] == "add_node"
        assert proj.executed_tools[0]["arguments"] == {"label": "A"}

    def test_emits_progress(self):
        proj, mocks = _make_projector()
        proj.on_tool_event("tool_start", "add_node", {}, None)
        mocks["emit_progress"].assert_called_with("tool_start", "Running add_node...", tool="add_node")

    def test_marks_interrupted_when_cancelled(self):
        proj, mocks = _make_projector(is_cancelled=True)
        proj.on_tool_event("tool_start", "add_node", {}, None)
        assert proj.executed_tools[0]["interrupted"] is True
        # Should NOT emit progress when cancelled
        mocks["emit_progress"].assert_not_called()


# ── tool_complete ────────────────────────────────────────

class TestToolComplete:
    def test_records_result(self):
        proj, _ = _make_projector()
        proj.on_tool_event("tool_start", "add_node", {}, None)
        proj.on_tool_event("tool_complete", "add_node", {}, {"success": True, "action": "add"})
        assert proj.executed_tools[0]["result"] == {"success": True, "action": "add"}
        assert proj.executed_tools[0]["success"] is True

    def test_skips_skipped_results(self):
        proj, mocks = _make_projector()
        proj.on_tool_event("tool_start", "add_node", {}, None)
        proj.on_tool_event("tool_complete", "add_node", {}, {"skipped": True})
        # No result should be recorded on the entry
        assert "result" not in proj.executed_tools[0]

    def test_snapshots_workflow_for_edit_tools(self):
        proj, mocks = _make_projector()
        proj.on_tool_event("tool_start", "add_node", {}, None)
        proj.on_tool_event("tool_complete", "add_node", {}, {"success": True, "action": "add"})
        mocks["conversation_logger"].log_workflow_snapshot.assert_called_once_with(
            "conv-1", {"nodes": []}, task_id="t1",
        )

    def test_no_snapshot_when_no_convo(self):
        proj, mocks = _make_projector(has_convo=False)
        proj.on_tool_event("tool_start", "add_node", {}, None)
        proj.on_tool_event("tool_complete", "add_node", {}, {"success": True, "action": "add"})
        mocks["conversation_logger"].log_workflow_snapshot.assert_not_called()


# ── tool_batch_complete ──────────────────────────────────

class TestToolBatchComplete:
    def test_flushes_summary_and_emits_thinking(self):
        proj, mocks = _make_projector()
        # Build up summary first
        proj.on_tool_event("tool_start", "add_node", {}, None)
        proj.on_tool_event("tool_complete", "add_node", {}, {"success": True, "action": "add"})
        proj.on_tool_event("tool_batch_complete", "", {}, None)
        # stream_chunk called with tool summary
        assert mocks["stream_chunk"].call_count >= 1
        # Progress updated to "Thinking..."
        mocks["emit_progress"].assert_any_call("thinking", "Thinking...")

    def test_no_thinking_when_cancelled(self):
        proj, mocks = _make_projector(is_cancelled=True)
        proj.on_tool_event("tool_batch_complete", "", {}, None)
        # Should not emit "thinking" progress
        for c in mocks["emit_progress"].call_args_list:
            assert c.args[0] != "thinking"


# ── WORKFLOW_EDIT_TOOLS projections ──────────────────────

class TestWorkflowEditProjections:
    def test_emits_workflow_update_and_state(self):
        proj, mocks = _make_projector()
        proj.on_tool_event("tool_start", "add_node", {}, None)
        proj.on_tool_event("tool_complete", "add_node", {}, {"success": True, "action": "add"})

        # Should emit workflow_update
        publish_calls = [c.args for c in mocks["publish"].call_args_list]
        events = [e for e, _ in publish_calls]
        assert "workflow_update" in events

        # Should publish workflow state
        mocks["publish_workflow_state"].assert_called()

    def test_emits_analysis_updated_on_variable_change(self):
        proj, mocks = _make_projector(
            workflow_analysis={"variables": [{"id": "v1"}], "outputs": []}
        )
        proj.on_tool_event("tool_start", "add_node", {}, None)
        proj.on_tool_event("tool_complete", "add_node", {}, {
            "success": True, "action": "add",
            "new_variables": [{"id": "v1", "name": "test"}],
        })
        publish_calls = [c.args for c in mocks["publish"].call_args_list]
        events = [e for e, _ in publish_calls]
        assert "analysis_updated" in events


# ── WORKFLOW_INPUT_TOOLS projections ─────────────────────

class TestWorkflowInputProjections:
    def test_emits_state_and_analysis(self):
        proj, mocks = _make_projector()
        proj.on_tool_event("tool_start", "add_workflow_variable", {}, None)
        proj.on_tool_event("tool_complete", "add_workflow_variable", {}, {"success": True})
        publish_calls = [c.args for c in mocks["publish"].call_args_list]
        events = [e for e, _ in publish_calls]
        assert "analysis_updated" in events
        mocks["publish_workflow_state"].assert_called()


# ── ask_question ─────────────────────────────────────────

class TestAskQuestion:
    def test_emits_pending_question(self):
        proj, mocks = _make_projector()
        proj.on_tool_event("tool_start", "ask_question", {}, None)
        proj.on_tool_event("tool_complete", "ask_question", {}, {
            "success": True,
            "questions": [{"question": "Pick one?", "options": ["A", "B"]}],
        })
        publish_calls = [c.args for c in mocks["publish"].call_args_list]
        pending = [(e, p) for e, p in publish_calls if e == "pending_question"]
        assert len(pending) == 1
        assert pending[0][1]["question"] == "Pick one?"


# ── save_workflow_to_library ─────────────────────────────

class TestSaveWorkflow:
    def test_emits_workflow_saved(self):
        proj, mocks = _make_projector()
        proj.on_tool_event("tool_start", "save_workflow_to_library", {}, None)
        proj.on_tool_event("tool_complete", "save_workflow_to_library", {}, {
            "success": True,
            "workflow_id": "wf-99",
            "name": "My Workflow",
        })
        publish_calls = [c.args for c in mocks["publish"].call_args_list]
        saved = [(e, p) for e, p in publish_calls if e == "workflow_saved"]
        assert len(saved) == 1
        assert saved[0][1]["workflow_id"] == "wf-99"
        assert saved[0][1]["is_draft"] is False


# ── cancellation suppression ────────────────────────────

class TestCancellation:
    def test_skips_sse_emissions_when_cancelled(self):
        proj, mocks = _make_projector(is_cancelled=True)
        proj.on_tool_event("tool_start", "add_node", {}, None)
        proj.on_tool_event("tool_complete", "add_node", {}, {"success": True, "action": "add"})
        # Should NOT emit workflow_update, workflow_state, etc.
        mocks["publish"].assert_not_called()
        mocks["publish_workflow_state"].assert_not_called()


# ── flush_tool_summary ──────────────────────────────────

class TestFlushToolSummary:
    def test_emits_summary_as_stream_chunk(self):
        proj, mocks = _make_projector()
        # Note a tool so the summary has content
        proj.tool_summary.note("add_node", success=True)
        proj.flush_tool_summary()
        mocks["stream_chunk"].assert_called_once()
        summary_text = mocks["stream_chunk"].call_args.args[0]
        # Summary is human-readable (e.g. "Added a workflow node"), not raw tool name
        assert len(summary_text) > 0

    def test_no_emit_when_empty(self):
        proj, mocks = _make_projector()
        proj.flush_tool_summary()
        mocks["stream_chunk"].assert_not_called()
