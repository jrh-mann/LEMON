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
from ...utils.uploads import load_annotations, save_annotations
from ...validation.tree_validator import TreeValidator
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
        ToolParameter(
            name="relationship",
            type="string",
            description="How the files relate and what to extract from each.",
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
        on_thinking = kwargs.get("on_thinking")
        session_state = kwargs.get("session_state") or {}
        session_id = args.get("session_id")
        feedback = args.get("feedback")
        file_classifications = args.get("files")  # List of {id, purpose}
        relationship = args.get("relationship")  # How files relate + extraction notes
        uploaded_files = session_state.get("uploaded_files", [])

        if should_cancel and should_cancel():
            raise CancellationError("Analyze workflow cancelled before execution.")

        # Path 1: Follow-up on existing session (unchanged)
        if session_id:
            return self._analyze_followup(session_id, feedback, stream, should_cancel, on_thinking=on_thinking)

        # Path 2: Multi-file analysis with classifications
        if file_classifications and uploaded_files:
            response = self._analyze_multi_file(
                uploaded_files, file_classifications, stream, should_cancel,
                on_progress=on_progress, relationship=relationship, on_thinking=on_thinking,
            )
        else:
            # Path 3: Single file analysis (existing behaviour)
            response = self._analyze_single_file(stream, should_cancel, on_thinking=on_thinking)

        # Post-process: create subworkflows from linked guidance
        response = self._process_subworkflows(response, session_state)
        return response

    def _analyze_followup(
        self,
        session_id: str,
        feedback: Optional[str],
        stream: Any,
        should_cancel: Any,
        on_thinking: Any = None,
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

        img_annotations = load_annotations(image_path, repo_root=self.repo_root)
        data = self.subagent.analyze(
            image_path=image_path,
            session_id=session_id,
            feedback=feedback,
            img_annotations=img_annotations or None,
            stream=stream,
            should_cancel=should_cancel,
            on_thinking=on_thinking,
        )
        return self._build_response(session_id, data, image_annotations=img_annotations, image_path=image_path)

    def _analyze_single_file(
        self,
        stream: Any,
        should_cancel: Any,
        on_thinking: Any = None,
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
        img_annotations = load_annotations(image_path, repo_root=self.repo_root)

        data = self.subagent.analyze(
            image_path=image_path,
            session_id=session_id,
            feedback=None,
            img_annotations=img_annotations or None,
            stream=stream,
            should_cancel=should_cancel,
            on_thinking=on_thinking,
        )
        return self._build_response(session_id, data, image_annotations=img_annotations, image_path=image_path)

    def _analyze_multi_file(
        self,
        uploaded_files: List[Dict[str, Any]],
        classifications: List[Dict[str, Any]],
        stream: Any,
        should_cancel: Any,
        on_progress: Any = None,
        relationship: Optional[str] = None,
        on_thinking: Any = None,
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
        # Create a session entry so follow-up feedback works.
        # Use the first file's name as the session image reference.
        first_file = classified_files[0]
        self.history.create_session(session_id, first_file.get("name", "multi-file"))

        data = self.subagent.analyze_multi(
            classified_files=classified_files,
            session_id=session_id,
            stream=stream,
            should_cancel=should_cancel,
            on_progress=on_progress,
            relationship=relationship,
            on_thinking=on_thinking,
        )
        # Multi-file has no single image_path for annotations, pass empty list
        return self._build_response(session_id, data, image_annotations=[])

    def _build_response(
        self, session_id: str, data: Dict[str, Any],
        image_annotations: List[Dict[str, Any]] = None,
        image_path: Path = None,
    ) -> Dict[str, Any]:
        """Normalize subagent output into the standard tool response.

        Args:
            image_annotations: Existing annotations loaded for this image. Used to
                deduplicate doubt-based annotations. Defaults to empty list.
            image_path: Absolute path to the image file, needed to persist new
                annotations back to disk.
        """
        if image_annotations is None:
            image_annotations = []

        if isinstance(data, dict) and "message" in data and "analysis" not in data:
            return {
                "session_id": session_id,
                "message": data.get("message", ""),
                "analysis": {"variables": [], "outputs": [], "tree": {}, "doubts": [], "reasoning": "", "guidance": []},
                "flowchart": {"nodes": [], "edges": []},
            }
        analysis = normalize_analysis(dict(data))
        flowchart = flowchart_from_tree(analysis.get("tree") or {})

        doubts = analysis.get("doubts", [])
        new_annotations = []
        if isinstance(doubts, list) and doubts:
            for doubt in doubts:
                if isinstance(doubt, dict) and "question" in doubt and "x" in doubt and "y" in doubt:
                    is_dup = False
                    for a in image_annotations:
                        if a.get("type") == "question" and a.get("question") == str(doubt["question"]):
                            if abs(a.get("x", 0) - doubt["x"]) < 10 and abs(a.get("y", 0) - doubt["y"]) < 10:
                                is_dup = True
                                break
                    if not is_dup:
                        ann = {
                            "id": uuid4().hex[:8],
                            "type": "question",
                            "x": doubt["x"],
                            "y": doubt["y"],
                            "question": str(doubt["question"]),
                            "status": "pending",
                        }
                        image_annotations.append(ann)
                        new_annotations.append(ann)

            if new_annotations and image_path:
                save_annotations(image_path, image_annotations, repo_root=self.repo_root)

        return {
            "session_id": session_id,
            "analysis": analysis,
            "flowchart": flowchart,
            "annotations": image_annotations,
        }

    # ------------------------------------------------------------------
    # Subworkflow post-processing
    # ------------------------------------------------------------------

    _tree_validator = TreeValidator()

    def _process_subworkflows(
        self,
        response: Dict[str, Any],
        session_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create real workflows from subworkflow definitions in the analysis.

        For each subworkflow entry in analysis["subworkflows"]:
        1. Validate the sub-tree
        2. Normalize inputs/tree
        3. Create workflow in WorkflowStore
        4. Replace the linked action node with a subprocess node (tree + flowchart)
        5. Register the output variable on the parent analysis

        All failures are non-blocking — the main analysis is always returned.
        """
        analysis = response.get("analysis")
        if not isinstance(analysis, dict):
            return response

        subworkflows = analysis.get("subworkflows")
        if not isinstance(subworkflows, list) or not subworkflows:
            return response

        # Lazy imports to avoid circular dependency (add_node -> workflow_input.add)
        from ..workflow_input.add import generate_variable_id
        from ..workflow_library.create_workflow import generate_workflow_id

        workflow_store = session_state.get("workflow_store")
        user_id = session_state.get("user_id")
        if not workflow_store:
            self._logger.warning("_process_subworkflows: no workflow_store in session_state, skipping")
            return response
        if not user_id:
            self._logger.warning("_process_subworkflows: no user_id in session_state, skipping")
            return response

        created: List[Dict[str, Any]] = []

        for idx, sub in enumerate(subworkflows):
            if not isinstance(sub, dict):
                continue

            # Validate required fields
            name = sub.get("name")
            linked_to_node = sub.get("linked_to_node")
            sub_tree = sub.get("tree")
            output_type = sub.get("output_type")
            output_variable = sub.get("output_variable")
            input_mapping = sub.get("input_mapping")
            if not all([name, linked_to_node, sub_tree, output_type, output_variable, input_mapping]):
                self._logger.warning(
                    "_process_subworkflows[%d]: missing required fields, skipping (name=%s)",
                    idx, name,
                )
                continue

            # Validate the sub-tree structure
            sub_analysis = {
                "tree": sub_tree,
                "variables": sub.get("inputs", []),
            }
            is_valid, errors = self._tree_validator.validate(sub_analysis)
            if not is_valid:
                self._logger.warning(
                    "_process_subworkflows[%d]: invalid sub-tree for '%s': %s",
                    idx, name, TreeValidator.format_errors(errors),
                )
                continue

            # Normalize sub-inputs and tree
            sub_data = normalize_analysis({
                "inputs": sub.get("inputs", []),
                "outputs": sub.get("outputs", []),
                "tree": sub_tree,
            })

            # Create workflow in the database
            workflow_id = generate_workflow_id()
            sub_flowchart = flowchart_from_tree(sub_data.get("tree") or {})
            try:
                workflow_store.create_workflow(
                    workflow_id=workflow_id,
                    user_id=user_id,
                    name=name,
                    description=f"Subworkflow for node '{linked_to_node}'",
                    nodes=sub_flowchart.get("nodes", []),
                    edges=sub_flowchart.get("edges", []),
                    inputs=sub_data.get("variables", []),
                    outputs=sub_data.get("outputs", []),
                    tree=sub_data.get("tree", {}),
                    output_type=output_type,
                    is_draft=False,
                )
            except Exception as exc:
                self._logger.error(
                    "_process_subworkflows[%d]: failed to create workflow '%s': %s",
                    idx, name, exc,
                )
                continue

            # Replace node in main flowchart (action "process" -> "subprocess")
            flowchart_nodes = response.get("flowchart", {}).get("nodes", [])
            node_found_in_flowchart = False
            for fnode in flowchart_nodes:
                if fnode.get("id") == linked_to_node:
                    fnode["type"] = "subprocess"
                    fnode["subworkflow_id"] = workflow_id
                    fnode["input_mapping"] = input_mapping
                    fnode["output_variable"] = output_variable
                    node_found_in_flowchart = True
                    break

            # Replace node in main tree (action -> subprocess)
            node_found_in_tree = self._replace_tree_node(
                analysis.get("tree", {}),
                linked_to_node,
                workflow_id,
                input_mapping,
                output_variable,
            )

            if not node_found_in_flowchart and not node_found_in_tree:
                self._logger.warning(
                    "_process_subworkflows[%d]: linked_to_node '%s' not found in tree or flowchart",
                    idx, linked_to_node,
                )

            # Register output variable on parent analysis
            var_id = generate_variable_id(output_variable, output_type, "subprocess")
            variables = analysis.get("variables", [])
            variables.append({
                "id": var_id,
                "name": output_variable,
                "type": output_type,
                "source": "subprocess",
                "source_node_id": linked_to_node,
                "subworkflow_id": workflow_id,
                "description": f"Output from subworkflow '{name}'",
            })
            analysis["variables"] = variables

            created.append({
                "workflow_id": workflow_id,
                "name": name,
                "linked_to_node": linked_to_node,
            })
            self._logger.info(
                "_process_subworkflows[%d]: created subworkflow '%s' (id=%s) for node '%s'",
                idx, name, workflow_id, linked_to_node,
            )

        # Attach created subworkflows list for visibility
        if created:
            response["created_subworkflows"] = created

        return response

    @staticmethod
    def _replace_tree_node(
        tree: Dict[str, Any],
        node_id: str,
        subworkflow_id: str,
        input_mapping: Dict[str, str],
        output_variable: str,
    ) -> bool:
        """Walk the nested tree and replace the node matching node_id with subprocess type.

        Returns True if the node was found and replaced.
        """
        start = tree.get("start")
        if not isinstance(start, dict):
            return False

        stack = [start]
        while stack:
            node = stack.pop()
            if node.get("id") == node_id:
                node["type"] = "subprocess"
                node["subworkflow_id"] = subworkflow_id
                node["input_mapping"] = input_mapping
                node["output_variable"] = output_variable
                return True
            for child in node.get("children", []):
                if isinstance(child, dict):
                    stack.append(child)
        return False

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
