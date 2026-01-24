"""Publish latest analysis tool."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from ...storage.history import HistoryStore
from ...utils.analysis import normalize_analysis
from ...utils.flowchart import flowchart_from_tree
from ...utils.paths import lemon_data_dir
from ..core import Tool, ToolParameter


class PublishLatestAnalysisTool(Tool):
    name = "publish_latest_analysis"
    description = "Load the most recent workflow analysis and return it for rendering on the canvas."
    parameters: List[ToolParameter] = []

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        history_db = lemon_data_dir(repo_root) / "history.sqlite"
        self.history = HistoryStore(history_db)
        self._logger = logging.getLogger(__name__)

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        self._logger.info("Executing publish_latest_analysis")
        latest = self.history.get_latest_analysis()
        if not latest:
            return {
                "session_id": "",
                "analysis": {
                    "inputs": [],
                    "outputs": [],
                    "tree": {},
                    "doubts": [
                        "No analysis found. Ask the user to upload an image and run workflow analysis."
                    ],
                },
                "flowchart": {"nodes": [], "edges": []},
            }

        session_id, analysis = latest
        analysis = normalize_analysis(analysis)
        flowchart = flowchart_from_tree(analysis.get("tree") or {})
        return {
            "session_id": session_id,
            "analysis": analysis,
            "flowchart": flowchart,
        }
