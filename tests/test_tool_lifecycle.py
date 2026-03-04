"""Integration test: full tool lifecycle.

Exercises all LLM-facing workflow tools sequentially, simulating what the
agent does when building a real workflow.  No API or LLM calls — tools are
called directly via .execute().

The test builds an "Age Check" workflow from scratch:
  create → configure variables → build nodes/edges → validate → execute →
  modify → cleanup → save

This catches regressions like the NameError in _validate_simple_condition
that broke all decision node creation.
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from uuid import uuid4

from src.backend.storage.workflows import WorkflowStore
from src.backend.tools.workflow_edit import (
    GetCurrentWorkflowTool,
    AddNodeTool,
    ModifyNodeTool,
    DeleteNodeTool,
    AddConnectionTool,
    DeleteConnectionTool,
    BatchEditWorkflowTool,
)
from src.backend.tools.workflow_input import (
    AddWorkflowVariableTool,
    ListWorkflowVariablesTool,
    ModifyWorkflowVariableTool,
    RemoveWorkflowVariableTool,
)
from src.backend.tools.workflow_output import SetWorkflowOutputTool
from src.backend.tools.validate_workflow import ValidateWorkflowTool
from src.backend.tools.execute_workflow import ExecuteWorkflowTool
from src.backend.tools.workflow_library.save_workflow import SaveWorkflowToLibrary
from src.backend.tools.workflow_library.list_workflows import ListWorkflowsInLibrary


class TestFullToolLifecycle:
    """Build a complete workflow using every tool, then execute it."""

    def setup_method(self):
        """Instantiate every tool once."""
        self.get_current = GetCurrentWorkflowTool()
        self.add_node = AddNodeTool()
        self.modify_node = ModifyNodeTool()
        self.delete_node = DeleteNodeTool()
        self.add_conn = AddConnectionTool()
        self.delete_conn = DeleteConnectionTool()
        self.batch_edit = BatchEditWorkflowTool()
        self.add_var = AddWorkflowVariableTool()
        self.list_vars = ListWorkflowVariablesTool()
        self.modify_var = ModifyWorkflowVariableTool()
        self.remove_var = RemoveWorkflowVariableTool()
        self.set_output = SetWorkflowOutputTool()
        self.validate = ValidateWorkflowTool()
        self.execute = ExecuteWorkflowTool()
        self.save_to_lib = SaveWorkflowToLibrary()
        self.list_lib = ListWorkflowsInLibrary()

    # ── helpers ──────────────────────────────────────────────────────

    def _create_workflow_in_db(self, workflow_store, user_id, name="Age Check"):
        """Simulate what ws_chat.py does: create a workflow record directly.

        The LLM never calls create_workflow — the WebSocket handler auto-
        creates the DB record when the frontend connects.
        """
        workflow_id = f"wf_{uuid4().hex}"
        workflow_store.create_workflow(
            workflow_id=workflow_id,
            user_id=user_id,
            name=name,
            description="",
            output_type="string",
        )
        return workflow_id

    def _run(self, tool, args, session_state, expect_success=True):
        """Call tool.execute() and assert success/failure."""
        result = tool.execute(args, session_state=session_state)
        if expect_success:
            assert result["success"] is True, (
                f"{tool.name} failed: {result.get('error')}"
            )
        else:
            assert result["success"] is False, (
                f"{tool.name} should have failed but succeeded: {result}"
            )
        return result

    # ── main lifecycle test ──────────────────────────────────────────

    def test_full_lifecycle(self, workflow_store, test_user_id, session_state):
        """Build, validate, execute, modify, and save a workflow."""

        # ── Step 1: Create workflow (simulates ws_chat auto-create) ──
        wf_id = self._create_workflow_in_db(workflow_store, test_user_id)
        args = {"workflow_id": wf_id}

        # ── Step 2: get_current_workflow — empty ──
        r = self._run(self.get_current, args, session_state)
        assert r["node_count"] == 0
        assert r["edge_count"] == 0

        # ── Step 3: list_workflows_in_library — workflow appears ──
        r = self._run(self.list_lib, {}, session_state)
        assert r["count"] >= 1
        ids = [w["id"] for w in r["workflows"]]
        assert wf_id in ids

        # ── Step 4: add_workflow_variable — "Age" (number) ──
        r = self._run(self.add_var, {
            "workflow_id": wf_id,
            "name": "Age",
            "type": "number",
            "range_min": 0,
            "range_max": 120,
        }, session_state)
        assert r["variable"]["name"] == "Age"
        assert r["variable"]["type"] == "number"

        # ── Step 5: add_workflow_variable — "Name" (string) ──
        r = self._run(self.add_var, {
            "workflow_id": wf_id,
            "name": "Name",
            "type": "string",
        }, session_state)
        assert r["variable"]["name"] == "Name"

        # ── Step 6: list_workflow_variables — 2 variables ──
        r = self._run(self.list_vars, args, session_state)
        names = [v["name"] for v in r["variables"]]
        assert "Age" in names
        assert "Name" in names
        assert len(r["variables"]) == 2

        # ── Step 7: modify_workflow_variable — rename Name → PatientName ──
        r = self._run(self.modify_var, {
            "workflow_id": wf_id,
            "name": "Name",
            "new_name": "PatientName",
        }, session_state)
        assert r["variable"]["name"] == "PatientName"

        # ── Step 8: list_workflow_variables — verify rename ──
        r = self._run(self.list_vars, args, session_state)
        names = [v["name"] for v in r["variables"]]
        assert "PatientName" in names
        assert "Name" not in names

        # ── Step 9: set_workflow_output ──
        r = self._run(self.set_output, {
            "workflow_id": wf_id,
            "name": "Result",
            "type": "string",
        }, session_state)
        assert r["output"]["name"] == "Result"
        assert r["output"]["type"] == "string"

        # ── Step 10: add_node (start) ──
        r = self._run(self.add_node, {
            "workflow_id": wf_id,
            "type": "start",
            "label": "Input",
        }, session_state)
        start_id = r["node"]["id"]
        assert r["node"]["type"] == "start"

        # ── Step 11: add_node (decision) — variable-name condition ──
        # Tests demand #1: use variable name "Age" instead of ID
        r = self._run(self.add_node, {
            "workflow_id": wf_id,
            "type": "decision",
            "label": "Age >= 18?",
            "condition": {
                "variable": "Age",
                "comparator": "gte",
                "value": 18,
            },
        }, session_state)
        decision_id = r["node"]["id"]
        assert r["node"]["type"] == "decision"
        # Verify variable name was resolved to input_id internally
        assert r["node"]["condition"]["input_id"] is not None

        # ── Step 12: add_node (end) — unified output as template ──
        # Tests demand #3: output="Adult: {PatientName}" → stored as output_template
        r = self._run(self.add_node, {
            "workflow_id": wf_id,
            "type": "end",
            "label": "Adult",
            "output": "Adult: {PatientName}",
        }, session_state)
        adult_id = r["node"]["id"]
        assert r["node"]["type"] == "end"
        assert r["node"].get("output_template") == "Adult: {PatientName}"

        # ── Step 13: add_node (end) — unified output as literal ──
        r = self._run(self.add_node, {
            "workflow_id": wf_id,
            "type": "end",
            "label": "Child",
            "output": "Minor",
        }, session_state)
        child_id = r["node"]["id"]
        assert r["node"]["type"] == "end"
        assert r["node"].get("output_value") == "Minor"

        # ── Step 14: add_connection — start → decision ──
        r = self._run(self.add_conn, {
            "workflow_id": wf_id,
            "from_node_id": start_id,
            "to_node_id": decision_id,
        }, session_state)
        assert r["edge"]["from"] == start_id
        assert r["edge"]["to"] == decision_id

        # ── Step 15: add_connection — decision → Adult (true) ──
        r = self._run(self.add_conn, {
            "workflow_id": wf_id,
            "from_node_id": decision_id,
            "to_node_id": adult_id,
            "label": "true",
        }, session_state)
        assert r["edge"]["label"] == "true"

        # ── Step 16: add_connection — decision → Child (false) ──
        r = self._run(self.add_conn, {
            "workflow_id": wf_id,
            "from_node_id": decision_id,
            "to_node_id": child_id,
            "label": "false",
        }, session_state)
        assert r["edge"]["label"] == "false"

        # ── Step 17: get_current_workflow — verify structure ──
        r = self._run(self.get_current, args, session_state)
        assert r["node_count"] == 4
        assert r["edge_count"] == 3

        # ── Step 18: validate_workflow — should pass strict ──
        r = self._run(self.validate, args, session_state)
        assert r["valid"] is True

        # ── Step 19: execute_workflow — Adult path ──
        r = self._run(self.execute, {
            "workflow_id": wf_id,
            "input_values": {"Age": 25, "PatientName": "Alice"},
        }, session_state)
        assert r["output"] == "Adult: Alice"
        assert len(r["path"]) == 3  # start → decision → adult

        # ── Step 20: execute_workflow — Child path ──
        r = self._run(self.execute, {
            "workflow_id": wf_id,
            "input_values": {"Age": 10, "PatientName": "Bob"},
        }, session_state)
        assert r["output"] == "Minor"
        assert len(r["path"]) == 3  # start → decision → child

        # ── Step 21: modify_node — resolve by label (tests resolve_node_id) ──
        r = self._run(self.modify_node, {
            "workflow_id": wf_id,
            "node_id": "Adult",  # label, not UUID
            "label": "Is Adult",
        }, session_state)
        assert r["node"]["label"] == "Is Adult"
        assert r["node"]["id"] == adult_id  # resolved to real ID

        # ── Step 22: delete_connection — decision → Child ──
        r = self._run(self.delete_conn, {
            "workflow_id": wf_id,
            "from_node_id": decision_id,
            "to_node_id": child_id,
        }, session_state)

        # ── Step 23: add_node (process) — "Log" node ──
        r = self._run(self.add_node, {
            "workflow_id": wf_id,
            "type": "process",
            "label": "Log",
        }, session_state)
        log_id = r["node"]["id"]

        # ── Step 24: batch_edit — reconnect via Log node ──
        # decision --(false)--> Log --> Child
        r = self._run(self.batch_edit, {
            "workflow_id": wf_id,
            "operations": [
                {
                    "op": "add_connection",
                    "from": decision_id,
                    "to": log_id,
                    "label": "false",
                },
                {
                    "op": "add_connection",
                    "from": log_id,
                    "to": child_id,
                },
            ],
        }, session_state)
        assert r["operation_count"] == 2

        # ── Step 25: add_node (calculation) — auto-register output var ──
        r = self._run(self.add_node, {
            "workflow_id": wf_id,
            "type": "calculation",
            "label": "Add Numbers",
            "calculation": {
                "output": {"name": "Sum"},
                "operator": "add",
                "operands": [
                    {"kind": "literal", "value": 1},
                    {"kind": "literal", "value": 2},
                ],
            },
        }, session_state)
        calc_id = r["node"]["id"]
        # Calculation node auto-registers an output variable
        assert len(r["new_variables"]) == 1
        assert r["new_variables"][0]["name"] == "Sum"
        assert r["new_variables"][0]["source"] == "calculated"

        # ── Step 26: delete_node — Log node, verify edge cascade ──
        r = self._run(self.delete_node, {
            "workflow_id": wf_id,
            "node_id": log_id,
        }, session_state)
        # Verify edges involving log_id were removed
        r2 = self._run(self.get_current, args, session_state)
        edge_nodes = set()
        for e in r2["workflow"]["edges"]:
            edge_nodes.add(e["from"])
            edge_nodes.add(e["to"])
        assert log_id not in edge_nodes

        # ── Step 27: remove_workflow_variable — force remove ──
        r = self._run(self.remove_var, {
            "workflow_id": wf_id,
            "name": "PatientName",
            "force": True,
        }, session_state)

        # Verify variable is gone
        r2 = self._run(self.list_vars, args, session_state)
        var_names = [v["name"] for v in r2["variables"] if v.get("source") == "input"]
        assert "PatientName" not in var_names

        # ── Step 28: save_workflow_to_library ──
        r = self._run(self.save_to_lib, {"workflow_id": wf_id}, session_state)
        assert r["already_saved"] is False

        # ── Step 29: list_workflows_in_library — verify saved ──
        r = self._run(self.list_lib, {}, session_state)
        saved_wf = next(w for w in r["workflows"] if w["id"] == wf_id)
        assert saved_wf["is_draft"] is False

    # ── error case tests ─────────────────────────────────────────────

    def test_bad_variable_ref_lists_available(self, workflow_store, test_user_id, session_state):
        """Demand #5: bad variable reference should list available variables."""
        wf_id = self._create_workflow_in_db(workflow_store, test_user_id)

        # Add a variable so the error message has something to list
        self._run(self.add_var, {
            "workflow_id": wf_id,
            "name": "Height",
            "type": "number",
        }, session_state)

        # Try to add a decision node referencing a nonexistent variable
        r = self._run(self.add_node, {
            "workflow_id": wf_id,
            "type": "decision",
            "label": "Bad Check",
            "condition": {
                "variable": "NonExistent",
                "comparator": "gte",
                "value": 10,
            },
        }, session_state, expect_success=False)

        # Error should mention available variables
        assert "NonExistent" in r["error"]
        assert "Height" in r["error"]

    def test_duplicate_variable_name_rejected(self, workflow_store, test_user_id, session_state):
        """Adding a variable with a duplicate name should fail."""
        wf_id = self._create_workflow_in_db(workflow_store, test_user_id)

        self._run(self.add_var, {
            "workflow_id": wf_id,
            "name": "Age",
            "type": "number",
        }, session_state)

        # Adding same name again should fail
        r = self._run(self.add_var, {
            "workflow_id": wf_id,
            "name": "Age",
            "type": "number",
        }, session_state, expect_success=False)
        assert "Age" in r["error"].lower() or "already exists" in r["error"].lower()

    def test_delete_nonexistent_node_fails(self, workflow_store, test_user_id, session_state):
        """Deleting a nonexistent node should fail with a clear error."""
        wf_id = self._create_workflow_in_db(workflow_store, test_user_id)

        r = self._run(self.delete_node, {
            "workflow_id": wf_id,
            "node_id": "nonexistent_node_id",
        }, session_state, expect_success=False)
        assert "error" in r


class TestUITools:
    """Test UI-only tools (highlight, ask_question, update_plan, view_image).

    These tools don't touch the DB — they return action payloads for the
    frontend.  extract_guidance is excluded because it makes an LLM call.
    """

    def setup_method(self):
        from src.backend.tools.workflow_edit.highlight import HighlightNodeTool
        from src.backend.tools.workflow_analysis.ask_question import AskQuestionTool
        from src.backend.tools.workflow_analysis.update_plan import UpdatePlanTool
        from src.backend.tools.workflow_analysis.view_image import ViewImageTool

        self.highlight = HighlightNodeTool()
        self.ask_question = AskQuestionTool()
        self.update_plan = UpdatePlanTool()
        self.view_image = ViewImageTool()

    # ── highlight_node ───────────────────────────────────────────────

    def test_highlight_node(self):
        """Should return highlight action payload."""
        r = self.highlight.execute({"node_id": "node_abc"})
        assert r["success"] is True
        assert r["action"] == "highlight_node"
        assert r["node_id"] == "node_abc"

    def test_highlight_node_missing_id(self):
        """Should fail when node_id is missing."""
        r = self.highlight.execute({})
        assert r["success"] is False
        assert "node_id" in r["error"]

    # ── ask_question ─────────────────────────────────────────────────

    def test_ask_question_with_options(self):
        """Should normalize questions and return them."""
        r = self.ask_question.execute({
            "questions": [
                {
                    "question": "What threshold for age?",
                    "options": [
                        {"label": "18", "value": "18"},
                        {"label": "21", "value": "21"},
                    ],
                },
            ],
        })
        assert r["success"] is True
        assert r["action"] == "question_asked"
        assert len(r["questions"]) == 1
        assert r["questions"][0]["question"] == "What threshold for age?"
        assert len(r["questions"][0]["options"]) == 2

    def test_ask_question_bare_strings(self):
        """Should accept bare strings as shorthand."""
        r = self.ask_question.execute({
            "questions": ["What is the patient's name?"],
        })
        assert r["success"] is True
        assert r["questions"][0]["question"] == "What is the patient's name?"
        assert r["questions"][0]["options"] == []

    def test_ask_question_empty_raises(self):
        """Should raise ValueError when no questions provided."""
        with pytest.raises(ValueError, match="questions"):
            self.ask_question.execute({"questions": []})

    def test_ask_question_multiple(self):
        """Should handle multiple questions in one call."""
        r = self.ask_question.execute({
            "questions": [
                {"question": "Q1?", "options": []},
                {"question": "Q2?", "options": [{"label": "Yes", "value": "yes"}]},
                "Q3?",
            ],
        })
        assert r["success"] is True
        assert len(r["questions"]) == 3

    # ── update_plan ──────────────────────────────────────────────────

    def test_update_plan(self):
        """Should return plan items."""
        r = self.update_plan.execute({
            "items": [
                {"text": "Add variables", "done": True},
                {"text": "Build decision tree", "done": False},
                {"text": "Validate workflow", "done": False},
            ],
        })
        assert r["success"] is True
        assert r["action"] == "plan_updated"
        assert len(r["items"]) == 3
        assert r["items"][0]["done"] is True
        assert r["items"][1]["done"] is False

    def test_update_plan_empty_items(self):
        """Should handle empty plan."""
        r = self.update_plan.execute({"items": []})
        assert r["success"] is True
        assert r["items"] == []

    def test_update_plan_invalid_items(self):
        """Should fail when items is not a list."""
        r = self.update_plan.execute({"items": "not a list"})
        assert r["success"] is False

    # ── view_image ───────────────────────────────────────────────────

    def test_view_image_returns_base64(self):
        """Should read image from disk and return base64-encoded content."""
        # Create a tiny 1x1 PNG (smallest valid PNG)
        png_bytes = (
            b'\x89PNG\r\n\x1a\n'  # PNG signature
            b'\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x02\x00\x00\x00\x90wS\xde'
            b'\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05'
            b'\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(png_bytes)
            img_path = f.name

        try:
            session_state = {
                "uploaded_files": [
                    {"name": "workflow.png", "path": img_path, "file_type": "image"},
                ],
            }
            r = self.view_image.execute({}, session_state=session_state)
            assert r["success"] is True
            assert len(r["content"]) == 2
            # First block is the image
            assert r["content"][0]["type"] == "image"
            assert r["content"][0]["source"]["media_type"] == "image/png"
            assert len(r["content"][0]["source"]["data"]) > 0  # base64 data
            # Second block is the caption
            assert r["content"][1]["type"] == "text"
            assert "workflow.png" in r["content"][1]["text"]
        finally:
            Path(img_path).unlink(missing_ok=True)

    def test_view_image_specific_filename(self):
        """Should select the correct image when filename is specified."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f1, \
             tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f2:
            # Write minimal PNG bytes to both
            png_bytes = (
                b'\x89PNG\r\n\x1a\n'
                b'\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
                b'\x08\x02\x00\x00\x00\x90wS\xde'
                b'\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05'
                b'\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
            )
            f1.write(png_bytes)
            f2.write(png_bytes)
            path1, path2 = f1.name, f2.name

        try:
            session_state = {
                "uploaded_files": [
                    {"name": "first.png", "path": path1, "file_type": "image"},
                    {"name": "second.png", "path": path2, "file_type": "image"},
                ],
            }
            r = self.view_image.execute(
                {"filename": "second.png"}, session_state=session_state,
            )
            assert r["success"] is True
            assert "second.png" in r["content"][1]["text"]
        finally:
            Path(path1).unlink(missing_ok=True)
            Path(path2).unlink(missing_ok=True)

    def test_view_image_no_images(self):
        """Should fail when no images are uploaded."""
        r = self.view_image.execute({}, session_state={"uploaded_files": []})
        assert r["success"] is False
        assert "No uploaded image" in r["error"]

    def test_view_image_missing_filename(self):
        """Should fail when requested filename doesn't exist."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b'\x89PNG\r\n\x1a\n')  # partial PNG, enough for name lookup
            img_path = f.name

        try:
            session_state = {
                "uploaded_files": [
                    {"name": "real.png", "path": img_path, "file_type": "image"},
                ],
            }
            r = self.view_image.execute(
                {"filename": "nonexistent.png"}, session_state=session_state,
            )
            assert r["success"] is False
            assert "nonexistent.png" in r["error"]
            assert "real.png" in r["error"]  # lists available images
        finally:
            Path(img_path).unlink(missing_ok=True)


class TestSubworkflowTools:
    """Test create_subworkflow and update_subworkflow.

    The background builder thread is mocked — we test the synchronous
    validation, DB creation, variable registration, and state transitions
    without making any LLM calls.
    """

    def setup_method(self):
        from src.backend.tools.workflow_analysis.create_subworkflow import (
            CreateSubworkflowTool,
        )
        from src.backend.tools.workflow_analysis.update_subworkflow import (
            UpdateSubworkflowTool,
        )

        self.create_sub = CreateSubworkflowTool()
        self.update_sub = UpdateSubworkflowTool()

    def _session(self, workflow_store, user_id):
        """Build a session_state with repo_root (required by subworkflow tools)."""
        return {
            "workflow_store": workflow_store,
            "user_id": user_id,
            "repo_root": "/fake/repo",  # just needs to be truthy
        }

    # ── create_subworkflow — validation ──────────────────────────────

    def test_create_missing_name(self, workflow_store, test_user_id):
        """Should reject when name is missing."""
        r = self.create_sub.execute(
            {"output_type": "string", "brief": "Build it", "inputs": []},
            session_state=self._session(workflow_store, test_user_id),
        )
        assert r["success"] is False
        assert r["error_code"] == "MISSING_NAME"

    def test_create_invalid_output_type(self, workflow_store, test_user_id):
        """Should reject invalid output_type."""
        r = self.create_sub.execute(
            {"name": "Test", "output_type": "invalid", "brief": "Build it", "inputs": []},
            session_state=self._session(workflow_store, test_user_id),
        )
        assert r["success"] is False
        assert r["error_code"] == "INVALID_OUTPUT_TYPE"

    def test_create_missing_brief(self, workflow_store, test_user_id):
        """Should reject when brief is missing."""
        r = self.create_sub.execute(
            {"name": "Test", "output_type": "number", "inputs": []},
            session_state=self._session(workflow_store, test_user_id),
        )
        assert r["success"] is False
        assert r["error_code"] == "MISSING_BRIEF"

    def test_create_invalid_inputs(self, workflow_store, test_user_id):
        """Should reject when inputs is not an array."""
        r = self.create_sub.execute(
            {"name": "Test", "output_type": "number", "brief": "Build it", "inputs": "bad"},
            session_state=self._session(workflow_store, test_user_id),
        )
        assert r["success"] is False
        assert r["error_code"] == "INVALID_INPUTS"

    def test_create_missing_repo_root(self, workflow_store, test_user_id):
        """Should reject when repo_root is not in session_state."""
        session = {"workflow_store": workflow_store, "user_id": test_user_id}
        r = self.create_sub.execute(
            {"name": "Test", "output_type": "number", "brief": "Build it", "inputs": []},
            session_state=session,
        )
        assert r["success"] is False
        assert r["error_code"] == "NO_REPO_ROOT"

    # ── create_subworkflow — success path ────────────────────────────

    @patch("src.backend.tools.workflow_analysis.create_subworkflow.threading.Thread")
    def test_create_success(self, mock_thread_cls, workflow_store, test_user_id):
        """Should create DB record, register variables, and spawn builder thread."""
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        r = self.create_sub.execute(
            {
                "name": "BMI Calculator",
                "output_type": "number",
                "brief": "Calculate BMI from height and weight",
                "inputs": [
                    {"name": "Height", "type": "number", "description": "Height in cm"},
                    {"name": "Weight", "type": "number", "description": "Weight in kg"},
                ],
            },
            session_state=self._session(workflow_store, test_user_id),
        )

        assert r["success"] is True
        assert r["status"] == "building"
        assert r["name"] == "BMI Calculator"
        assert r["output_type"] == "number"
        wf_id = r["workflow_id"]
        assert wf_id.startswith("wf_")

        # Verify input variables were registered
        assert len(r["registered_inputs"]) == 2
        names = [inp["name"] for inp in r["registered_inputs"]]
        assert "Height" in names
        assert "Weight" in names

        # Verify workflow exists in DB with building=True
        wf = workflow_store.get_workflow(wf_id, test_user_id)
        assert wf is not None
        assert wf.name == "BMI Calculator"
        assert wf.building is True
        assert wf.output_type == "number"

        # Verify variables were persisted in DB
        assert len(wf.inputs) == 2
        var_names = [v["name"] for v in wf.inputs]
        assert "Height" in var_names
        assert "Weight" in var_names

        # Verify background thread was spawned
        mock_thread_cls.assert_called_once()
        mock_thread.start.assert_called_once()
        # Thread target should be _run_subworkflow_builder
        call_kwargs = mock_thread_cls.call_args
        assert call_kwargs.kwargs["daemon"] is True
        assert "subworkflow-builder" in call_kwargs.kwargs["name"]

    @patch("src.backend.tools.workflow_analysis.create_subworkflow.threading.Thread")
    def test_create_empty_inputs(self, mock_thread_cls, workflow_store, test_user_id):
        """Should succeed with no input variables."""
        mock_thread_cls.return_value = MagicMock()

        r = self.create_sub.execute(
            {
                "name": "Constant Workflow",
                "output_type": "string",
                "brief": "Always returns hello",
                "inputs": [],
            },
            session_state=self._session(workflow_store, test_user_id),
        )

        assert r["success"] is True
        assert r["registered_inputs"] == []
        # Still creates the workflow
        wf = workflow_store.get_workflow(r["workflow_id"], test_user_id)
        assert wf is not None

    @patch("src.backend.tools.workflow_analysis.create_subworkflow.threading.Thread")
    def test_create_skips_invalid_inputs(self, mock_thread_cls, workflow_store, test_user_id):
        """Should skip malformed input entries without failing."""
        mock_thread_cls.return_value = MagicMock()

        r = self.create_sub.execute(
            {
                "name": "Partial Inputs",
                "output_type": "string",
                "brief": "Test with bad inputs",
                "inputs": [
                    {"name": "Good", "type": "string"},
                    "not_a_dict",  # should be skipped
                    {"no_name_key": True},  # should be skipped
                ],
            },
            session_state=self._session(workflow_store, test_user_id),
        )

        assert r["success"] is True
        # Only "Good" should be registered
        assert len(r["registered_inputs"]) == 1
        assert r["registered_inputs"][0]["name"] == "Good"

    # ── update_subworkflow — validation ──────────────────────────────

    def test_update_missing_workflow_id(self, workflow_store, test_user_id):
        """Should reject when workflow_id is missing."""
        r = self.update_sub.execute(
            {"instructions": "Change the threshold"},
            session_state=self._session(workflow_store, test_user_id),
        )
        assert r["success"] is False
        assert r["error_code"] == "MISSING_WORKFLOW_ID"

    def test_update_missing_instructions(self, workflow_store, test_user_id):
        """Should reject when instructions is missing."""
        r = self.update_sub.execute(
            {"workflow_id": "wf_abc"},
            session_state=self._session(workflow_store, test_user_id),
        )
        assert r["success"] is False
        assert r["error_code"] == "MISSING_INSTRUCTIONS"

    def test_update_missing_repo_root(self, workflow_store, test_user_id):
        """Should reject when repo_root is not in session_state."""
        session = {"workflow_store": workflow_store, "user_id": test_user_id}
        r = self.update_sub.execute(
            {"workflow_id": "wf_abc", "instructions": "Fix it"},
            session_state=session,
        )
        assert r["success"] is False
        assert r["error_code"] == "NO_REPO_ROOT"

    def test_update_workflow_not_found(self, workflow_store, test_user_id):
        """Should fail when workflow doesn't exist."""
        r = self.update_sub.execute(
            {"workflow_id": "wf_nonexistent", "instructions": "Fix it"},
            session_state=self._session(workflow_store, test_user_id),
        )
        assert r["success"] is False
        assert r["error_code"] == "NOT_FOUND"

    def test_update_rejects_while_building(self, workflow_store, test_user_id):
        """Should reject update when workflow is still being built."""
        # Create a workflow with building=True
        wf_id = f"wf_{uuid4().hex}"
        workflow_store.create_workflow(
            workflow_id=wf_id,
            user_id=test_user_id,
            name="Building WF",
            description="",
            output_type="string",
            building=True,
        )

        r = self.update_sub.execute(
            {"workflow_id": wf_id, "instructions": "Change something"},
            session_state=self._session(workflow_store, test_user_id),
        )
        assert r["success"] is False
        assert r["error_code"] == "STILL_BUILDING"

    # ── update_subworkflow — success path ────────────────────────────

    @patch("src.backend.tools.workflow_analysis.update_subworkflow.threading.Thread")
    def test_update_success(self, mock_thread_cls, workflow_store, test_user_id):
        """Should mark as building, spawn updater thread, and return immediately."""
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        # Create a finished workflow (building=False)
        wf_id = f"wf_{uuid4().hex}"
        workflow_store.create_workflow(
            workflow_id=wf_id,
            user_id=test_user_id,
            name="Credit Score",
            description="Calculates credit score",
            output_type="number",
            building=False,
        )

        r = self.update_sub.execute(
            {"workflow_id": wf_id, "instructions": "Add a new threshold at 700"},
            session_state=self._session(workflow_store, test_user_id),
        )

        assert r["success"] is True
        assert r["status"] == "updating"
        assert r["name"] == "Credit Score"
        assert r["workflow_id"] == wf_id

        # Verify building flag was set in DB
        wf = workflow_store.get_workflow(wf_id, test_user_id)
        assert wf.building is True

        # Verify background thread was spawned
        mock_thread_cls.assert_called_once()
        mock_thread.start.assert_called_once()
        call_kwargs = mock_thread_cls.call_args
        assert call_kwargs.kwargs["daemon"] is True
        assert "subworkflow-updater" in call_kwargs.kwargs["name"]

    # ── full create → update lifecycle ───────────────────────────────

    @patch("src.backend.tools.workflow_analysis.update_subworkflow.threading.Thread")
    @patch("src.backend.tools.workflow_analysis.create_subworkflow.threading.Thread")
    def test_create_then_update_lifecycle(
        self, mock_create_thread_cls, mock_update_thread_cls,
        workflow_store, test_user_id,
    ):
        """Full lifecycle: create subworkflow, simulate build completion, then update."""
        mock_create_thread_cls.return_value = MagicMock()
        mock_update_thread_cls.return_value = MagicMock()

        # Step 1: Create subworkflow
        r1 = self.create_sub.execute(
            {
                "name": "Risk Assessment",
                "output_type": "string",
                "brief": "Assess patient risk level",
                "inputs": [
                    {"name": "Age", "type": "number"},
                    {"name": "Smoker", "type": "bool"},
                ],
            },
            session_state=self._session(workflow_store, test_user_id),
        )
        assert r1["success"] is True
        wf_id = r1["workflow_id"]

        # Verify it's in building state
        wf = workflow_store.get_workflow(wf_id, test_user_id)
        assert wf.building is True

        # Step 2: Try to update while building — should fail
        r2 = self.update_sub.execute(
            {"workflow_id": wf_id, "instructions": "Add BMI check"},
            session_state=self._session(workflow_store, test_user_id),
        )
        assert r2["success"] is False
        assert r2["error_code"] == "STILL_BUILDING"

        # Step 3: Simulate build completion (background thread would do this)
        workflow_store.update_workflow(
            wf_id, test_user_id,
            building=False,
            build_history=[{"role": "user", "content": "Build it"}],
        )

        # Step 4: Now update should succeed
        r3 = self.update_sub.execute(
            {"workflow_id": wf_id, "instructions": "Add BMI check"},
            session_state=self._session(workflow_store, test_user_id),
        )
        assert r3["success"] is True
        assert r3["status"] == "updating"

        # Verify building flag was set again
        wf = workflow_store.get_workflow(wf_id, test_user_id)
        assert wf.building is True
