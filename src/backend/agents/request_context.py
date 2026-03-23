from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .orchestrator import Orchestrator
from ..storage.workflows import WorkflowStore
from ..utils.image import file_to_data_url
from ..utils.paths import lemon_data_dir


def hydrate_uploaded_files(
    *,
    workflow_store: WorkflowStore,
    user_id: str,
    workflow_id: str,
    repo_root: Path,
) -> List[Dict[str, Any]]:
    record = workflow_store.get_workflow(workflow_id, user_id)
    if not record or not record.uploaded_files:
        return []

    data_dir = lemon_data_dir(repo_root)
    uploaded_files: List[Dict[str, Any]] = []
    for file_info in record.uploaded_files:
        rel_path = file_info.get("rel_path")
        if not isinstance(rel_path, str) or not rel_path:
            continue
        try:
            abs_path = data_dir / rel_path
            uploaded_files.append(
                {
                    "name": file_info.get("name", ""),
                    "path": str(abs_path),
                    "file_type": file_info.get("file_type", "image"),
                    "purpose": file_info.get("purpose", "unclassified"),
                    "data_url": file_to_data_url(abs_path),
                }
            )
        except Exception:
            continue
    return uploaded_files


def configure_orchestrator_for_request(
    orchestrator: Orchestrator,
    *,
    workflow_store: WorkflowStore,
    user_id: str,
    current_workflow_id: Optional[str],
    repo_root: Path,
    open_tabs: Optional[List[Dict[str, Any]]] = None,
    uploaded_files: Optional[List[Dict[str, Any]]] = None,
    workflow_data: Optional[Dict[str, Any]] = None,
    workflow_analysis: Optional[Dict[str, Any]] = None,
    refresh_from_db: bool = False,
) -> Orchestrator:
    orchestrator.workflow_store = workflow_store
    orchestrator.user_id = user_id
    orchestrator.current_workflow_id = current_workflow_id
    orchestrator.repo_root = repo_root
    orchestrator.open_tabs = open_tabs or []
    orchestrator.uploaded_files = uploaded_files or []
    orchestrator.current_workflow = workflow_data or {"nodes": [], "edges": []}
    orchestrator.workflow_analysis = workflow_analysis or {
        "variables": [],
        "outputs": [],
    }
    if refresh_from_db and current_workflow_id:
        orchestrator.refresh_workflow_from_db()
    return orchestrator
