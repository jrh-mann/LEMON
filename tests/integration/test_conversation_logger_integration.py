"""Integration test for ConversationLogger ↔ WsChatTask logging flow.

Mimics the exact sequence of calls that WsChatTask.run() and
on_tool_event() make to the ConversationLogger, verifying entries
are persisted correctly.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.backend.storage.conversation_log import ConversationLogger


@pytest.fixture()
def logger(tmp_path: Path) -> ConversationLogger:
    """Fresh ConversationLogger backed by a temp SQLite file."""
    return ConversationLogger(tmp_path / "test_integration.sqlite")


CONV_ID = "conv-integration-001"
USER_ID = "user-99"
WORKFLOW_ID = "wf_abc123"
MODEL = "claude-sonnet-4-6"
TASK_ID = "task-xyz"


class TestWsChatTaskFlow:
    """Simulates the exact logging sequence from WsChatTask.run()."""

    def test_full_chat_turn(self, logger: ConversationLogger) -> None:
        """Simulates a single chat turn: user message → tool calls → response.

        This mirrors the code path in WsChatTask.run() and on_tool_event():
        1. ensure_conversation (run, line ~448)
        2. log_user_message (run, line ~459)
        3. log_tool_call × N (on_tool_event, line ~233)
        4. log_workflow_snapshot (on_tool_event, line ~239)
        5. log_assistant_response (run, line ~478)
        6. log_thinking (run, line ~485)
        """
        # Step 1: ensure_conversation (called at start of run())
        logger.ensure_conversation(
            CONV_ID, user_id=USER_ID, workflow_id=WORKFLOW_ID, model=MODEL,
        )

        # Step 2: log_user_message (called in run())
        logger.log_user_message(
            CONV_ID, "Please analyse and build this workflow",
            files=[{"name": "flowchart.png", "file_type": "image"}],
            task_id=TASK_ID,
        )

        # Step 3: log_tool_call (called from on_tool_event for each tool)
        logger.log_tool_call(
            CONV_ID, "extract_guidance",
            {"filename": "flowchart.png"},
            {"success": True, "guidance": []},
            True, 2500.0,
            task_id=TASK_ID,
        )
        logger.log_tool_call(
            CONV_ID, "add_workflow_variable",
            {"name": "Temp", "type": "number"},
            {"success": True, "variable": {"id": "var_temp", "name": "Temp"}},
            True, 150.0,
            task_id=TASK_ID,
        )
        logger.log_tool_call(
            CONV_ID, "batch_edit_workflow",
            {"operations": [{"op": "add_node"}]},
            {"success": True, "workflow": {"nodes": [{"id": "n1"}], "edges": []}},
            True, 300.0,
            task_id=TASK_ID,
        )

        # Step 4: log_workflow_snapshot (called after edit tools)
        logger.log_workflow_snapshot(
            CONV_ID,
            {"nodes": [{"id": "n1", "type": "start"}], "edges": []},
            task_id=TASK_ID,
        )

        # Step 5: log_assistant_response (called after respond() returns)
        logger.log_assistant_response(
            CONV_ID, "Workflow built successfully!",
            input_tokens=15000, output_tokens=200,
            task_id=TASK_ID,
        )

        # Step 6: log_thinking (if extended thinking was used)
        logger.log_thinking(
            CONV_ID, "I need to build a temperature check workflow...",
            task_id=TASK_ID,
        )

        # Verify all entries were persisted
        entries = logger.get_conversation_timeline(CONV_ID)
        assert len(entries) == 7, f"Expected 7 entries, got {len(entries)}"

        # Verify entry types in order
        types = [e["entry_type"] for e in entries]
        assert types == [
            "user_message",
            "tool_call", "tool_call", "tool_call",
            "workflow_snapshot",
            "assistant_response",
            "thinking",
        ]

        # Verify user message content
        user_msg = entries[0]
        assert user_msg["role"] == "user"
        assert "analyse and build" in user_msg["content"]
        assert user_msg["task_id"] == TASK_ID

        # Verify tool calls
        tool_calls = [e for e in entries if e["entry_type"] == "tool_call"]
        assert tool_calls[0]["tool_name"] == "extract_guidance"
        assert tool_calls[1]["tool_name"] == "add_workflow_variable"
        assert tool_calls[2]["tool_name"] == "batch_edit_workflow"
        assert all(e["tool_success"] == 1 for e in tool_calls)
        assert tool_calls[0]["tool_duration_ms"] == 2500.0

        # Verify assistant response
        response = entries[5]
        assert response["role"] == "assistant"
        assert response["input_tokens"] == 15000
        assert response["output_tokens"] == 200

        # Verify conversation record
        convos = logger.list_conversations()
        assert len(convos) == 1
        assert convos[0]["id"] == CONV_ID
        assert convos[0]["user_id"] == USER_ID
        assert convos[0]["workflow_id"] == WORKFLOW_ID

    def test_second_turn_reuses_conversation(self, logger: ConversationLogger) -> None:
        """Verify that a second chat turn appends to the same conversation."""
        # Turn 1
        logger.ensure_conversation(
            CONV_ID, user_id=USER_ID, workflow_id=WORKFLOW_ID, model=MODEL,
        )
        logger.log_user_message(CONV_ID, "Build a workflow", task_id="t1")
        logger.log_assistant_response(CONV_ID, "Done!", task_id="t1")

        # Turn 2 — same conversation, new task
        logger.ensure_conversation(
            CONV_ID, user_id=USER_ID, workflow_id=WORKFLOW_ID, model=MODEL,
        )
        logger.log_user_message(CONV_ID, "Remove the end node", task_id="t2")
        logger.log_tool_call(
            CONV_ID, "delete_node", {"node_id": "n5"},
            {"success": True, "node_id": "n5"}, True, 50.0,
            task_id="t2",
        )
        logger.log_assistant_response(CONV_ID, "End node removed.", task_id="t2")

        entries = logger.get_conversation_timeline(CONV_ID)
        assert len(entries) == 5

        # Sequences are monotonic across turns
        seqs = [e["seq"] for e in entries]
        assert seqs == [1, 2, 3, 4, 5]

        # Only 1 conversation record (not duplicated)
        convos = logger.list_conversations()
        assert len(convos) == 1

    def test_tool_call_stats_aggregation(self, logger: ConversationLogger) -> None:
        """Verify tool_call_stats work after a realistic session."""
        logger.ensure_conversation(
            CONV_ID, user_id=USER_ID, workflow_id=WORKFLOW_ID, model=MODEL,
        )
        # Simulate the pattern from the temperature workflow session
        tools = [
            ("extract_guidance", True, 2500.0),
            ("update_plan", True, 100.0),
            ("add_workflow_variable", True, 150.0),
            ("update_plan", True, 100.0),
            ("batch_edit_workflow", True, 300.0),
            ("update_plan", True, 100.0),
            ("set_workflow_output", True, 200.0),
            ("validate_workflow", True, 180.0),
            ("update_plan", True, 100.0),
        ]
        for tool_name, success, duration in tools:
            logger.log_tool_call(
                CONV_ID, tool_name, {}, {"success": success},
                success, duration, task_id=TASK_ID,
            )

        stats = logger.get_tool_call_stats(conversation_id=CONV_ID)
        stats_by_name = {s["tool_name"]: s for s in stats}

        assert stats_by_name["update_plan"]["call_count"] == 4
        assert stats_by_name["extract_guidance"]["call_count"] == 1
        assert stats_by_name["batch_edit_workflow"]["avg_duration_ms"] == 300.0

    def test_failed_tool_call_logged(self, logger: ConversationLogger) -> None:
        """Verify failed tool calls are logged with success=0."""
        logger.ensure_conversation(
            CONV_ID, user_id=USER_ID, workflow_id=WORKFLOW_ID, model=MODEL,
        )
        logger.log_tool_call(
            CONV_ID, "add_node",
            {"type": "decision", "label": "Check temp"},
            {"success": False, "error": "Variable 'temp' not found"},
            False, 50.0,
            task_id=TASK_ID,
        )

        entries = logger.get_conversation_timeline(CONV_ID, entry_types=["tool_call"])
        assert len(entries) == 1
        assert entries[0]["tool_success"] == 0
        assert "not found" in entries[0]["tool_result"]


class TestGuardConditions:
    """Verify behavior when logger or conversation is missing."""

    def test_logger_writes_to_correct_path(self, tmp_path: Path) -> None:
        """Verify entries end up in the specified database file."""
        db_path = tmp_path / "specific.sqlite"
        lgr = ConversationLogger(db_path)
        lgr.ensure_conversation("c1", user_id="u1", model=MODEL)
        lgr.log_user_message("c1", "test")

        # Verify the file exists and has data
        assert db_path.exists()
        entries = lgr.get_conversation_timeline("c1")
        assert len(entries) == 1

    def test_ensure_conversation_idempotent(self, logger: ConversationLogger) -> None:
        """Calling ensure_conversation multiple times doesn't duplicate."""
        for _ in range(5):
            logger.ensure_conversation(
                CONV_ID, user_id=USER_ID, workflow_id=WORKFLOW_ID, model=MODEL,
            )
        convos = logger.list_conversations()
        assert len(convos) == 1
