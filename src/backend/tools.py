"""Tool definitions for the backend."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .history import HistoryStore
from .subagent import Subagent


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

    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class AnalyzeWorkflowTool(Tool):
    name = "analyze_workflow"
    description = (
        "Analyze a workflow image and return JSON with inputs, outputs, a tree, and doubts."
    )
    parameters = [
        ToolParameter(
            name="image_name",
            type="string",
            description="Filename of the image in the repo root (e.g., workflow.jpeg).",
            required=False,
        ),
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

    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        self._logger.info(
            "Executing analyze_workflow args_keys=%s",
            sorted(args.keys()),
        )
        session_id = args.get("session_id")
        feedback = args.get("feedback")
        image_name = args.get("image_name")

        if session_id:
            if not feedback:
                raise ValueError(
                    "feedback is required when continuing a session with session_id"
                )
            stored_image = self.history.get_session_image(session_id)
            if not stored_image:
                raise ValueError(f"Unknown session_id: {session_id}")
            image_name = stored_image
        elif not image_name:
            raise ValueError("image_name is required when session_id is not provided")

        image_path = self.repo_root / image_name
        if not image_path.exists():
            # Try common extensions if none provided.
            if "." not in image_name:
                candidates = []
                for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"]:
                    cand = self.repo_root / f"{image_name}{ext}"
                    if cand.exists():
                        image_path = cand
                        image_name = cand.name
                        break
                    candidates.append(cand.name)
                else:
                    raise FileNotFoundError(
                        f"Image not found: {image_path}. Tried: {', '.join(candidates)}"
                    )
            else:
                raise FileNotFoundError(f"Image not found: {image_path}")

        if not session_id:
            session_id = uuid4().hex
            self.history.create_session(session_id, image_name)

        data = self.subagent.analyze(
            image_path=image_path,
            session_id=session_id,
            feedback=feedback,
        )
        analysis = dict(data)
        analysis.pop("tree", None)
        return {"session_id": session_id, "analysis": analysis}


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def execute(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")
        return tool.execute(args)
