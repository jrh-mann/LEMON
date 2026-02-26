"""Analyze workflow tool."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from ...agents.subagent import Subagent
from ...storage.history import HistoryStore
from ...utils.analysis import normalize_analysis
from ...utils.cancellation import CancellationError
from ...utils.flowchart import flowchart_from_tree
from ...utils.paths import lemon_data_dir
from ...utils.uploads import load_annotations
from ..core import Tool, ToolParameter


class AnalyzeWorkflowTool(Tool):
    name = "analyze_workflow"
    description = (
        "Analyze a workflow image and return JSON with inputs, outputs, a tree, and doubts."
    )
    parameters = [
        ToolParameter(
            name="session_id",
            type="string",
            description="Optional session id to continue a prior analysis.",
            required=False,
        ),
        ToolParameter(
            name="feedback",
            type="string",
            description="Optional feedback to refine the analysis.",
            required=False,
        ),
        ToolParameter(
            name="files",
            type="array",
            description="Classifications for uploaded files (id + purpose). Required for multi-file analysis.",
            required=False,
        ),
    ]

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        # Store analysis sessions and uploads under lemon_data_dir() so deployments can
        # override storage location via LEMON_DATA_DIR (common in Azure/App Service).
        self.data_dir = lemon_data_dir(repo_root)
        history_db = self.data_dir / "history.sqlite"
        self.history = HistoryStore(history_db)
        self.subagent = Subagent(self.history)
        self._logger = logging.getLogger(__name__)

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        self._logger.info(
            "Executing analyze_workflow args_keys=%s",
            sorted(args.keys()),
        )
        stream = kwargs.get("stream")
        should_cancel = kwargs.get("should_cancel")
        on_progress = kwargs.get("on_progress")
        session_state = kwargs.get("session_state") or {}
        session_id = args.get("session_id")
        feedback = args.get("feedback")
        file_classifications = args.get("files")  # List of {id, purpose}
        uploaded_files = session_state.get("uploaded_files", [])

        if should_cancel and should_cancel():
            raise CancellationError("Analyze workflow cancelled before execution.")

        # Path 1: Follow-up on existing session (unchanged)
        if session_id:
            return self._analyze_followup(session_id, feedback, stream, should_cancel)

        # Path 2: Multi-file analysis with classifications
        if file_classifications and uploaded_files:
            return self._analyze_multi_file(
                uploaded_files, file_classifications, stream, should_cancel,
                on_progress=on_progress,
            )

        # Path 3: Single file analysis (existing behaviour)
        return self._analyze_single_file(stream, should_cancel)

    def _analyze_followup(
        self,
        session_id: str,
        feedback: Optional[str],
        stream: Any,
        should_cancel: Any,
    ) -> Dict[str, Any]:
        """Continue a prior analysis session with feedback."""
        if not feedback:
            raise ValueError(
                "feedback is required when continuing a session with session_id"
            )
        stored_image = self.history.get_session_image(session_id)
        if not stored_image:
            raise ValueError(f"Unknown session_id: {session_id}")
        image_path = Path(stored_image)
        if not image_path.is_absolute():
            image_path = self.data_dir / stored_image
        if not image_path.exists():
            return self._missing_image_response()

        annotations = load_annotations(image_path, repo_root=self.repo_root)
        data = self.subagent.analyze(
            image_path=image_path,
            session_id=session_id,
            feedback=feedback,
            annotations=annotations or None,
            stream=stream,
            should_cancel=should_cancel,
        )
        return self._build_response(session_id, data)

    def _analyze_single_file(
        self,
        stream: Any,
        should_cancel: Any,
    ) -> Dict[str, Any]:
        """Analyze the most recently uploaded file (single file flow)."""
        file_name = self._latest_uploaded_file()
        if not file_name:
            return self._missing_image_response()

        image_path = Path(file_name)
        if not image_path.is_absolute():
            image_path = self.data_dir / file_name
        if not image_path.exists():
            return self._missing_image_response()

        session_id = uuid4().hex
        self.history.create_session(session_id, file_name)
        annotations = load_annotations(image_path, repo_root=self.repo_root)

        data = self.subagent.analyze(
            image_path=image_path,
            session_id=session_id,
            feedback=None,
            annotations=annotations or None,
            stream=stream,
            should_cancel=should_cancel,
        )
        return self._build_response(session_id, data)

    def _analyze_multi_file(
        self,
        uploaded_files: List[Dict[str, Any]],
        classifications: List[Dict[str, Any]],
        stream: Any,
        should_cancel: Any,
        on_progress: Any = None,
    ) -> Dict[str, Any]:
        """Analyze multiple files with classification-aware two-phase ordering.

        Builds a lookup from file id to file info, resolves absolute paths,
        then delegates to the subagent's analyze_multi method.
        """
        # Build lookups: by id and by name (fallback for when LLM uses names)
        id_lookup: Dict[str, Dict[str, Any]] = {
            f.get("id", ""): f for f in uploaded_files
        }
        name_lookup: Dict[str, Dict[str, Any]] = {
            f.get("name", ""): f for f in uploaded_files
        }

        # Match classifications to files and resolve absolute paths
        classified_files: List[Dict[str, Any]] = []
        for cls in classifications:
            file_id = cls.get("id", "")
            purpose = cls.get("purpose", "flowchart")
            # Try matching by id first, then fall back to matching by name
            file_info = id_lookup.get(file_id) or name_lookup.get(file_id)
            if not file_info:
                self._logger.warning("File classification references unknown id/name: %s", file_id)
                continue

            rel_path = file_info.get("path", "")
            abs_path = Path(rel_path)
            if not abs_path.is_absolute():
                abs_path = self.data_dir / rel_path
            if not abs_path.exists():
                self._logger.warning("Classified file not found: %s", abs_path)
                continue

            classified_files.append({
                "id": file_id,
                "name": file_info.get("name", ""),
                "abs_path": str(abs_path),
                "file_type": file_info.get("file_type", "image"),
                "purpose": purpose,
            })

        if not classified_files:
            return self._missing_image_response()

        session_id = uuid4().hex

        data = self.subagent.analyze_multi(
            classified_files=classified_files,
            session_id=session_id,
            stream=stream,
            should_cancel=should_cancel,
            on_progress=on_progress,
        )
        return self._build_response(session_id, data)

    def _build_response(
        self, session_id: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Normalize subagent output into the standard tool response."""
        if isinstance(data, dict) and "message" in data and "analysis" not in data:
            return {
                "session_id": session_id,
                "message": data.get("message", ""),
                "analysis": {"variables": [], "outputs": [], "tree": {}, "doubts": [], "reasoning": "", "guidance": []},
                "flowchart": {"nodes": [], "edges": []},
            }
        analysis = normalize_analysis(dict(data))
        flowchart = flowchart_from_tree(analysis.get("tree") or {})
        return {
            "session_id": session_id,
            "analysis": analysis,
            "flowchart": flowchart,
        }

    def _latest_uploaded_file(self) -> Optional[str]:
        """Find the most recently uploaded file (image or PDF)."""
        uploads_dir = self.data_dir / "uploads"
        if not uploads_dir.exists():
            return None
        candidates = [
            p
            for p in uploads_dir.iterdir()
            if p.is_file() and p.suffix.lower() in {
                ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".pdf"
            }
        ]
        if not candidates:
            return None
        latest = max(candidates, key=lambda p: p.stat().st_mtime)
        try:
            return str(latest.relative_to(self.data_dir))
        except ValueError:
            return str(latest)

    def _missing_image_response(self) -> Dict[str, Any]:
        return {
            "session_id": "",
            "analysis": {
                "variables": [],
                "outputs": [],
                "tree": {},
                "doubts": ["User hasn't uploaded image, ask them to upload image."],
                "reasoning": "",
                "guidance": [],
            },
            "flowchart": {"nodes": [], "edges": []},
        }
