"""Tool definitions for the backend."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .history import HistoryStore
from .subagent import Subagent


def _map_node_type(raw_type: str) -> str:
    mapped = {
        "action": "process",
    }
    return mapped.get(raw_type, raw_type)


def _flowchart_from_tree(tree: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    if not tree:
        return {"nodes": [], "edges": []}

    start = tree.get("start")
    if not isinstance(start, dict):
        return {"nodes": [], "edges": []}

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    seen = set()
    stack = [start]

    while stack:
        node = stack.pop()
        node_id = node.get("id")
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)

        raw_type = str(node.get("type") or "process")
        node_type = _map_node_type(raw_type)
        nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "label": node.get("label") or node_id,
                # Top-left coordinates; frontend auto-layout will adjust.
                "x": 0,
                "y": 0,
            }
        )

        for child in node.get("children") or []:
            child_id = child.get("id")
            if not child_id:
                continue
            edges.append(
                {
                    "id": f"{node_id}->{child_id}",
                    "from": node_id,
                    "to": child_id,
                    "label": child.get("edge_label") or "",
                }
            )
            stack.append(child)

    return {"nodes": nodes, "edges": edges}


@dataclass
class ToolParameter:
    name: str
    type: str
    description: str
    required: bool = True


class Tool:
    name: str
    description: str
    parameters: List[ToolParameter]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        raise NotImplementedError


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
    ]

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        history_db = repo_root / ".lemon" / "history.sqlite"
        self.history = HistoryStore(history_db)
        self.subagent = Subagent(self.history)
        self._logger = logging.getLogger(__name__)

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        self._logger.info(
            "Executing analyze_workflow args_keys=%s",
            sorted(args.keys()),
        )
        stream = kwargs.get("stream")
        session_id = args.get("session_id")
        feedback = args.get("feedback")

        if session_id:
            if not feedback:
                raise ValueError(
                    "feedback is required when continuing a session with session_id"
                )
            stored_image = self.history.get_session_image(session_id)
            if not stored_image:
                raise ValueError(f"Unknown session_id: {session_id}")
            image_name = stored_image
        else:
            image_name = self._latest_uploaded_image()
            if not image_name:
                return self._missing_image_response()

        image_path = self.repo_root / image_name
        if not image_path.exists():
            return self._missing_image_response()

        if not session_id:
            session_id = uuid4().hex
            self.history.create_session(session_id, image_name)

        data = self.subagent.analyze(
            image_path=image_path,
            session_id=session_id,
            feedback=feedback,
            stream=stream,
        )
        analysis = dict(data)
        flowchart = _flowchart_from_tree(analysis.get("tree") or {})
        return {
            "session_id": session_id,
            "analysis": analysis,
            "flowchart": flowchart,
        }

    def _latest_uploaded_image(self) -> Optional[str]:
        uploads_dir = self.repo_root / ".lemon" / "uploads"
        if not uploads_dir.exists():
            return None
        candidates = [
            p
            for p in uploads_dir.iterdir()
            if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
        ]
        if not candidates:
            return None
        latest = max(candidates, key=lambda p: p.stat().st_mtime)
        try:
            return str(latest.relative_to(self.repo_root))
        except ValueError:
            return None

    def _missing_image_response(self) -> Dict[str, Any]:
        return {
            "session_id": "",
            "analysis": {
                "inputs": [],
                "outputs": [],
                "tree": {},
                "doubts": ["User hasn't uploaded image, ask them to upload image."],
            },
            "flowchart": {"nodes": [], "edges": []},
        }


class PublishLatestAnalysisTool(Tool):
    name = "publish_latest_analysis"
    description = "Load the most recent workflow analysis and return it for rendering on the canvas."
    parameters: List[ToolParameter] = []

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        history_db = repo_root / ".lemon" / "history.sqlite"
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
        flowchart = _flowchart_from_tree(analysis.get("tree") or {})
        return {
            "session_id": session_id,
            "analysis": analysis,
            "flowchart": flowchart,
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def execute(self, name: str, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")
        return tool.execute(args, **kwargs)
