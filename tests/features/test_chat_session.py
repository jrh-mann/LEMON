"""Tests for chat_session — bootstrap and sync helpers.

Covers:
1. save_uploaded_files: saves files, handles errors, saves annotations
2. sync_payload_workflow: pushes workflow/analysis into conversation
3. ensure_workflow_persisted: persists snapshot, emits workflow_created
4. sync_orchestrator_from_convo: wires up orchestrator references
5. sync_convo_from_orchestrator: pushes orchestrator state back
6. persist_conversation_metadata: writes conversation_id + files to workflow
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.backend.tasks.chat_session import (
    save_uploaded_files,
    sync_payload_workflow,
    ensure_workflow_persisted,
    sync_orchestrator_from_convo,
    sync_convo_from_orchestrator,
    persist_conversation_metadata,
)


# ── save_uploaded_files ──────────────────────────────────

class TestSaveUploadedFiles:
    def test_returns_true_for_empty_list(self):
        ok, paths = save_uploaded_files(
            files_data=[], repo_root=Path("/tmp"),
            img_annotations=None, emit_error=MagicMock(),
        )
        assert ok is True
        assert paths == []

    @patch("src.backend.tasks.chat_session.save_uploaded_file")
    @patch("src.backend.tasks.chat_session.lemon_data_dir")
    def test_saves_file_and_returns_paths(self, mock_data_dir, mock_save):
        mock_save.return_value = ("uploads/test.png", "image")
        mock_data_dir.return_value = Path("/tmp/data")

        ok, paths = save_uploaded_files(
            files_data=[{"id": "f1", "name": "test.png", "data_url": "data:image/png;base64,abc"}],
            repo_root=Path("/tmp"),
            img_annotations=None,
            emit_error=MagicMock(),
        )
        assert ok is True
        assert len(paths) == 1
        assert paths[0]["name"] == "test.png"
        assert paths[0]["file_type"] == "image"

    @patch("src.backend.tasks.chat_session.save_uploaded_file")
    def test_emits_error_on_failure(self, mock_save):
        mock_save.side_effect = ValueError("bad data URL")
        emit_error = MagicMock()

        ok, paths = save_uploaded_files(
            files_data=[{"id": "f1", "name": "bad.png", "data_url": "garbage"}],
            repo_root=Path("/tmp"),
            img_annotations=None,
            emit_error=emit_error,
        )
        assert ok is False
        assert paths == []
        emit_error.assert_called_once()

    def test_skips_empty_data_url(self):
        ok, paths = save_uploaded_files(
            files_data=[{"id": "f1", "name": "empty.png", "data_url": ""}],
            repo_root=Path("/tmp"),
            img_annotations=None,
            emit_error=MagicMock(),
        )
        assert ok is True
        assert paths == []


# ── sync_payload_workflow ────────────────────────────────

class TestSyncPayloadWorkflow:
    def test_updates_workflow_and_analysis(self):
        convo = MagicMock()
        sync_payload_workflow(convo, {"nodes": [1]}, {"variables": []})
        convo.update_workflow_state.assert_called_once_with({"nodes": [1]})
        convo.update_workflow_analysis.assert_called_once_with({"variables": []})

    def test_skips_none_values(self):
        convo = MagicMock()
        sync_payload_workflow(convo, None, None)
        convo.update_workflow_state.assert_not_called()
        convo.update_workflow_analysis.assert_not_called()


# ── ensure_workflow_persisted ────────────────────────────

class TestEnsureWorkflowPersisted:
    @patch("src.backend.tasks.chat_session.persist_workflow_snapshot")
    def test_persists_and_emits_created(self, mock_persist):
        mock_persist.return_value = (True, {"outputs": [], "output_type": "string"})
        convo = MagicMock()
        convo.workflow = {"nodes": [], "edges": [], "variables": [], "outputs": [], "output_type": "string"}
        ws = MagicMock()
        ws.get_workflow.return_value = MagicMock(name="Test WF")
        publish = MagicMock()

        ensure_workflow_persisted(
            convo=convo, workflow_id="wf-1", user_id="u1",
            workflow_store=ws, publish=publish,
        )

        # Should emit workflow_created since created=True
        publish.assert_called_once()
        assert publish.call_args.args[0] == "workflow_created"
        # Should set orchestrator workflow_id
        assert convo.orchestrator.current_workflow_id == "wf-1"

    @patch("src.backend.tasks.chat_session.persist_workflow_snapshot")
    def test_no_event_when_not_created(self, mock_persist):
        mock_persist.return_value = (False, {"outputs": [], "output_type": "string"})
        convo = MagicMock()
        convo.workflow = {"nodes": [], "edges": [], "variables": [], "outputs": [], "output_type": "string"}
        ws = MagicMock()
        ws.get_workflow.return_value = None
        publish = MagicMock()

        ensure_workflow_persisted(
            convo=convo, workflow_id="wf-1", user_id="u1",
            workflow_store=ws, publish=publish,
        )
        publish.assert_not_called()


# ── sync_orchestrator_from_convo ─────────────────────────

class TestSyncOrchestratorFromConvo:
    @patch("src.backend.tasks.chat_session.ensure_workflow_persisted")
    def test_wires_up_orchestrator(self, mock_ensure):
        convo = MagicMock()
        sink = MagicMock()
        publish = MagicMock()

        sync_orchestrator_from_convo(
            convo=convo, workflow_id="wf-1", user_id="u1",
            repo_root=Path("/tmp"), workflow_store=MagicMock(),
            event_sink=sink, open_tabs=[{"id": "tab1"}],
            conversation_logger=MagicMock(), publish=publish,
        )

        assert convo.orchestrator.user_id == "u1"
        assert convo.orchestrator.repo_root == Path("/tmp")
        assert convo.orchestrator.event_sink == sink
        assert convo.orchestrator.open_tabs == [{"id": "tab1"}]
        mock_ensure.assert_called_once()


# ── sync_convo_from_orchestrator ─────────────────────────

class TestSyncConvoFromOrchestrator:
    def test_pushes_state_back(self):
        convo = MagicMock()
        convo.orchestrator.current_workflow = {"nodes": [1]}
        convo.orchestrator.workflow_analysis = {"variables": []}
        sync_convo_from_orchestrator(convo)
        convo.update_workflow_state.assert_called_once_with({"nodes": [1]})
        convo.update_workflow_analysis.assert_called_once_with({"variables": []})


# ── persist_conversation_metadata ────────────────────────

class TestPersistConversationMetadata:
    def test_persists_conversation_id(self):
        convo = MagicMock()
        convo.id = "conv-1"
        ws = MagicMock()

        persist_conversation_metadata(
            workflow_id="wf-1", user_id="u1", convo=convo,
            workflow_store=ws, repo_root=Path("/tmp"),
            saved_file_paths=[],
        )

        ws.update_workflow.assert_called_once_with("wf-1", "u1", conversation_id="conv-1")

    def test_handles_failure_gracefully(self):
        convo = MagicMock()
        convo.id = "conv-1"
        ws = MagicMock()
        ws.update_workflow.side_effect = RuntimeError("DB error")

        # Should not raise — logs a warning instead
        persist_conversation_metadata(
            workflow_id="wf-1", user_id="u1", convo=convo,
            workflow_store=ws, repo_root=Path("/tmp"),
            saved_file_paths=[],
        )
