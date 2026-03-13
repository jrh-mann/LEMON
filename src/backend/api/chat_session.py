"""Chat session helpers — bootstrap and sync functions for ChatTask.

Extracted from ChatTask. Each function takes explicit arguments rather
than accessing self.*, making dependencies visible and enabling isolated
testing. ChatTask keeps thin one-line delegates.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .conversations import Conversation
from .sse import EventSink
from ..storage.conversation_log import ConversationLogger
from ..storage.workflows import WorkflowStore
from ..utils.uploads import save_uploaded_file, save_annotations
from ..utils.paths import lemon_data_dir
from ..workflow_persistence import persist_workflow_snapshot

logger = logging.getLogger("backend.api")


def save_uploaded_files(
    *,
    files_data: List[Dict[str, Any]],
    repo_root: Path,
    img_annotations: Optional[List[Dict[str, Any]]],
    emit_error: Callable[[str], None],
) -> tuple[bool, List[Dict[str, Any]]]:
    """Save all uploaded files to disk.

    Returns (success, saved_file_paths). On failure, emits an error
    event and returns (False, []).
    """
    logger.info("save_uploaded_files: files_data count=%d", len(files_data))
    if not files_data:
        return True, []

    saved: List[Dict[str, Any]] = []
    for file_info in files_data:
        data_url = file_info.get("data_url", "")
        logger.info(
            "save_uploaded_files: processing file id=%s name=%s data_url_len=%d",
            file_info.get("id", "?"), file_info.get("name", "?"),
            len(data_url) if isinstance(data_url, str) else 0,
        )
        if not isinstance(data_url, str) or not data_url.strip():
            logger.warning("save_uploaded_files: skipping file with empty data_url: %s", file_info.get("name"))
            continue
        try:
            rel_path, file_type = save_uploaded_file(data_url, repo_root=repo_root)
            abs_path = str(lemon_data_dir(repo_root) / rel_path)
            saved.append({
                "id": file_info.get("id", ""),
                "name": file_info.get("name", ""),
                "path": abs_path,
                "file_type": file_type,
                "purpose": file_info.get("purpose", "unclassified"),
            })
        except Exception as exc:
            logger.exception("Failed to save uploaded file: %s", file_info.get("name"))
            emit_error(f"Invalid file '{file_info.get('name', '?')}': {exc}")
            return False, []

    # Save image annotations if present
    if img_annotations and isinstance(img_annotations, list) and saved:
        first_image = next(
            (f for f in saved if f["file_type"] == "image"), None
        )
        if first_image:
            save_annotations(first_image["path"], img_annotations, repo_root=repo_root)

    return True, saved


def sync_payload_workflow(
    convo: Conversation,
    workflow: Optional[Dict[str, Any]],
    analysis: Optional[Dict[str, Any]],
) -> None:
    """Push frontend payload workflow/analysis into the conversation."""
    if isinstance(workflow, dict):
        convo.update_workflow_state(workflow)
    if isinstance(analysis, dict):
        convo.update_workflow_analysis(analysis)


def ensure_workflow_persisted(
    *,
    convo: Conversation,
    workflow_id: str,
    user_id: str,
    workflow_store: WorkflowStore,
    publish: Callable[[str, dict], None],
) -> None:
    """Persist the canvas workflow snapshot to the database.

    If a new workflow row is created, emits a workflow_created event.
    Updates orchestrator's workflow_id and workflow_name.
    """
    workflow = convo.workflow
    try:
        created, persisted = persist_workflow_snapshot(
            workflow_store,
            workflow_id=workflow_id,
            user_id=user_id,
            name="New Workflow",
            description="",
            nodes=workflow.get("nodes", []),
            edges=workflow.get("edges", []),
            variables=workflow.get("variables", []),
            outputs=workflow.get("outputs", []),
            output_type=workflow.get("output_type", "string"),
            is_draft=True,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Failed to persist canvas workflow {workflow_id}: {exc}"
        ) from exc

    convo.workflow["outputs"] = persisted["outputs"]
    convo.workflow["output_type"] = persisted["output_type"]
    logger.info("Persisted canvas workflow snapshot %s for user %s", workflow_id, user_id)

    if created:
        publish("workflow_created", {
            "workflow_id": workflow_id,
            "name": "New Workflow",
            "output_type": persisted["output_type"],
            "is_draft": True,
        })

    convo.orchestrator.current_workflow_id = workflow_id
    # Look up workflow name from DB for system prompt display
    record = workflow_store.get_workflow(workflow_id, user_id)
    if record:
        convo.orchestrator.current_workflow_name = record.name


def sync_orchestrator_from_convo(
    *,
    convo: Conversation,
    workflow_id: Optional[str],
    user_id: str,
    repo_root: Path,
    workflow_store: WorkflowStore,
    event_sink: EventSink,
    open_tabs: Optional[List[Dict[str, Any]]],
    conversation_logger: Optional[ConversationLogger],
    publish: Callable[[str, dict], None],
) -> None:
    """Wire up the orchestrator from the conversation object.

    Syncs workflow state, analysis, store references, event sink,
    persists the workflow, and injects the conversation logger.
    """
    convo.orchestrator.sync_workflow(lambda: convo.workflow_state)
    convo.orchestrator.sync_workflow_analysis(lambda: convo.workflow_analysis)
    convo.orchestrator.workflow_store = workflow_store
    convo.orchestrator.user_id = user_id
    convo.orchestrator.repo_root = repo_root
    # Pass the EventSink so subworkflow tools can push fire-and-forget
    # notifications (subworkflow_created, subworkflow_ready) to the
    # parent's SSE stream. Builders create their own independent sinks.
    convo.orchestrator.event_sink = event_sink
    # Ensure the canvas workflow snapshot exists in the database
    if workflow_id and workflow_store:
        ensure_workflow_persisted(
            convo=convo,
            workflow_id=workflow_id,
            user_id=user_id,
            workflow_store=workflow_store,
            publish=publish,
        )
    convo.orchestrator.open_tabs = open_tabs or []
    # Inject conversation logger so the orchestrator can log compaction events
    convo.orchestrator.conversation._conversation_logger = conversation_logger
    convo.orchestrator.conversation._conversation_id = convo.id


def sync_convo_from_orchestrator(convo: Conversation) -> None:
    """Push orchestrator state back into the conversation after a turn."""
    convo.update_workflow_state(convo.orchestrator.current_workflow)
    convo.update_workflow_analysis(convo.orchestrator.workflow_analysis)


def persist_conversation_metadata(
    *,
    workflow_id: str,
    user_id: str,
    convo: Conversation,
    workflow_store: WorkflowStore,
    repo_root: Path,
    saved_file_paths: List[Dict[str, Any]],
) -> None:
    """Persist conversation_id and uploaded file metadata on the workflow."""
    try:
        update_kwargs: Dict[str, Any] = {"conversation_id": convo.id}
        if saved_file_paths:
            data_dir = lemon_data_dir(repo_root)
            uploaded_files = []
            for fp in saved_file_paths:
                abs_p = Path(fp["path"])
                try:
                    rel = str(abs_p.relative_to(data_dir))
                except ValueError:
                    rel = fp["path"]
                uploaded_files.append({
                    "name": fp.get("name", ""),
                    "rel_path": rel,
                    "file_type": fp.get("file_type", "image"),
                    "purpose": fp.get("purpose", "unclassified"),
                })
            update_kwargs["uploaded_files"] = uploaded_files
        workflow_store.update_workflow(workflow_id, user_id, **update_kwargs)
    except Exception:
        logger.warning(
            "Failed to persist conversation_id/files on workflow %s — "
            "chat may not survive page refresh",
            workflow_id,
            exc_info=True,
        )
