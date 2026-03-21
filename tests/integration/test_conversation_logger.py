"""Integration tests for ConversationLogger.

Validates roundtrip persistence, idempotency, sequence numbering,
thread safety, tool-call aggregation, and compaction logging.
"""

from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path

import pytest

from src.backend.storage.conversation_log import ConversationLogger


@pytest.fixture()
def logger(tmp_path: Path) -> ConversationLogger:
    """Fresh ConversationLogger backed by a temp SQLite file."""
    return ConversationLogger(tmp_path / "test_conversation_log.sqlite")


CONV_ID = "conv-test-001"
USER_ID = "user-42"
MODEL = "claude-sonnet-4-6"


# ------------------------------------------------------------------
# Roundtrip: create, log several entry types, read back
# ------------------------------------------------------------------

class TestRoundtrip:
    def test_full_lifecycle(self, logger: ConversationLogger) -> None:
        """Log a user message, assistant response, tool call, thinking,
        and workflow snapshot — then read them all back in order."""
        logger.ensure_conversation(
            CONV_ID, user_id=USER_ID, workflow_id="wf-1", model=MODEL,
        )

        s1 = logger.log_user_message(
            CONV_ID, "Build me a workflow", files=[{"name": "img.png"}], task_id="t1",
        )
        s2 = logger.log_assistant_response(
            CONV_ID,
            "Sure, let me add a node.",
            input_tokens=100,
            output_tokens=50,
            cache_creation_tokens=10,
            cache_read_tokens=5,
        )
        s3 = logger.log_tool_call(
            CONV_ID,
            "add_node",
            {"label": "Preprocess"},
            {"success": True, "node_id": "n1"},
            True,
            42.5,
            task_id="t1",
        )
        s4 = logger.log_thinking(CONV_ID, "I should add a preprocess step.")
        s5 = logger.log_workflow_snapshot(
            CONV_ID,
            {"nodes": [{"id": "n1"}], "edges": [], "variables": [], "outputs": []},
        )

        # Sequences are monotonically increasing starting at 1.
        assert [s1, s2, s3, s4, s5] == [1, 2, 3, 4, 5]

        timeline = logger.get_conversation_timeline(CONV_ID)
        assert len(timeline) == 5
        types = [e["entry_type"] for e in timeline]
        assert types == [
            "user_message",
            "assistant_response",
            "tool_call",
            "thinking",
            "workflow_snapshot",
        ]

        # Verify specific field persistence.
        user_msg = timeline[0]
        assert user_msg["role"] == "user"
        assert user_msg["content"] == "Build me a workflow"
        assert json.loads(user_msg["files"]) == [{"name": "img.png"}]
        assert user_msg["task_id"] == "t1"

        assistant = timeline[1]
        assert assistant["input_tokens"] == 100
        assert assistant["output_tokens"] == 50
        assert assistant["cache_creation_tokens"] == 10
        assert assistant["cache_read_tokens"] == 5

        tool = timeline[2]
        assert tool["tool_name"] == "add_node"
        assert json.loads(tool["tool_arguments"]) == {"label": "Preprocess"}
        assert tool["tool_success"] == 1
        assert tool["tool_duration_ms"] == pytest.approx(42.5)

        snapshot = timeline[4]
        wf = json.loads(snapshot["workflow_snapshot"])
        assert wf["nodes"][0]["id"] == "n1"

    def test_filter_by_entry_type(self, logger: ConversationLogger) -> None:
        """get_conversation_timeline with entry_types filter."""
        logger.ensure_conversation(CONV_ID, user_id=USER_ID, model=MODEL)
        logger.log_user_message(CONV_ID, "hello")
        logger.log_assistant_response(CONV_ID, "hi")
        logger.log_tool_call(CONV_ID, "t", {}, {}, True, 1.0)

        tool_only = logger.get_conversation_timeline(
            CONV_ID, entry_types=["tool_call"],
        )
        assert len(tool_only) == 1
        assert tool_only[0]["entry_type"] == "tool_call"


# ------------------------------------------------------------------
# Idempotent ensure_conversation
# ------------------------------------------------------------------

class TestIdempotentEnsure:
    def test_call_twice_get_one_row(self, logger: ConversationLogger) -> None:
        logger.ensure_conversation(CONV_ID, user_id=USER_ID, model=MODEL)
        logger.ensure_conversation(CONV_ID, user_id=USER_ID, model=MODEL)

        convos = logger.list_conversations(user_id=USER_ID)
        assert len(convos) == 1
        assert convos[0]["id"] == CONV_ID


# ------------------------------------------------------------------
# Sequence monotonicity
# ------------------------------------------------------------------

class TestSequenceMonotonicity:
    def test_seq_1_to_n(self, logger: ConversationLogger) -> None:
        """Log N entries and verify seqs are exactly 1..N."""
        logger.ensure_conversation(CONV_ID, user_id=USER_ID, model=MODEL)
        n = 20
        seqs = [
            logger.log_user_message(CONV_ID, f"msg-{i}") for i in range(n)
        ]
        assert seqs == list(range(1, n + 1))

    def test_seq_survives_new_instance(self, tmp_path: Path) -> None:
        """Sequence numbering picks up where it left off after restart."""
        db = tmp_path / "restart.sqlite"
        lg1 = ConversationLogger(db)
        lg1.ensure_conversation(CONV_ID, user_id=USER_ID, model=MODEL)
        lg1.log_user_message(CONV_ID, "first")
        lg1.log_user_message(CONV_ID, "second")

        # Simulate restart — new instance, same DB file.
        lg2 = ConversationLogger(db)
        seq = lg2.log_user_message(CONV_ID, "third")
        assert seq == 3


# ------------------------------------------------------------------
# Thread safety
# ------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_logging(self, logger: ConversationLogger) -> None:
        """10 threads × 50 entries — all present with unique seqs."""
        logger.ensure_conversation(CONV_ID, user_id=USER_ID, model=MODEL)
        n_threads = 10
        entries_per_thread = 50

        results: list[list[int]] = [[] for _ in range(n_threads)]

        def worker(idx: int) -> None:
            for i in range(entries_per_thread):
                seq = logger.log_user_message(CONV_ID, f"t{idx}-m{i}")
                results[idx].append(seq)

        threads = [
            threading.Thread(target=worker, args=(i,)) for i in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Every seq should be unique.
        all_seqs = [s for r in results for s in r]
        assert len(all_seqs) == n_threads * entries_per_thread
        assert len(set(all_seqs)) == len(all_seqs), "Duplicate sequence numbers!"

        # Seqs should be 1..total.
        assert sorted(all_seqs) == list(
            range(1, n_threads * entries_per_thread + 1)
        )

        # All entries persisted.
        timeline = logger.get_conversation_timeline(CONV_ID)
        assert len(timeline) == n_threads * entries_per_thread


# ------------------------------------------------------------------
# Tool call stats
# ------------------------------------------------------------------

class TestToolCallStats:
    def test_aggregation(self, logger: ConversationLogger) -> None:
        logger.ensure_conversation(CONV_ID, user_id=USER_ID, model=MODEL)

        # 3 successes, 2 failures for "add_node"
        for i in range(3):
            logger.log_tool_call(CONV_ID, "add_node", {}, {}, True, 10.0)
        for i in range(2):
            logger.log_tool_call(CONV_ID, "add_node", {}, {}, False, 20.0)

        # 1 success for "remove_node"
        logger.log_tool_call(CONV_ID, "remove_node", {}, {}, True, 5.0)

        stats = logger.get_tool_call_stats(conversation_id=CONV_ID)
        assert len(stats) == 2

        add = next(s for s in stats if s["tool_name"] == "add_node")
        assert add["call_count"] == 5
        assert add["success_count"] == 3
        assert add["failure_count"] == 2

        rm = next(s for s in stats if s["tool_name"] == "remove_node")
        assert rm["call_count"] == 1
        assert rm["success_count"] == 1
        assert rm["failure_count"] == 0


# ------------------------------------------------------------------
# Compaction logging
# ------------------------------------------------------------------

class TestCompactionLogging:
    def test_discarded_messages_preserved(self, logger: ConversationLogger) -> None:
        logger.ensure_conversation(CONV_ID, user_id=USER_ID, model=MODEL)

        old_msgs = [
            {"role": "user", "content": "old-1"},
            {"role": "assistant", "content": "old-2"},
        ]
        seq = logger.log_compaction(
            CONV_ID,
            original_count=10,
            summary="Summarised 8 messages into 1",
            discarded_messages=old_msgs,
        )
        assert seq == 1

        timeline = logger.get_conversation_timeline(
            CONV_ID, entry_types=["compaction"],
        )
        assert len(timeline) == 1
        payload = json.loads(timeline[0]["content"])
        assert payload["original_count"] == 10
        assert payload["summary"] == "Summarised 8 messages into 1"
        assert payload["discarded_messages"] == old_msgs


# ------------------------------------------------------------------
# Error logging
# ------------------------------------------------------------------

class TestErrorLogging:
    def test_error_entry(self, logger: ConversationLogger) -> None:
        logger.ensure_conversation(CONV_ID, user_id=USER_ID, model=MODEL)
        seq = logger.log_error(CONV_ID, "Boom!", task_id="t-err")
        assert seq == 1

        timeline = logger.get_conversation_timeline(
            CONV_ID, entry_types=["error"],
        )
        assert len(timeline) == 1
        assert timeline[0]["content"] == "Boom!"
        assert timeline[0]["task_id"] == "t-err"


# ------------------------------------------------------------------
# list_conversations filtering
# ------------------------------------------------------------------

class TestListConversations:
    def test_filter_by_workflow(self, logger: ConversationLogger) -> None:
        logger.ensure_conversation("c1", user_id="u1", workflow_id="wf-A", model=MODEL)
        logger.ensure_conversation("c2", user_id="u1", workflow_id="wf-B", model=MODEL)
        logger.ensure_conversation("c3", user_id="u2", workflow_id="wf-A", model=MODEL)

        by_wf = logger.list_conversations(workflow_id="wf-A")
        assert {c["id"] for c in by_wf} == {"c1", "c3"}

        by_user = logger.list_conversations(user_id="u1")
        assert {c["id"] for c in by_user} == {"c1", "c2"}

    def test_pagination(self, logger: ConversationLogger) -> None:
        for i in range(5):
            logger.ensure_conversation(f"c{i}", user_id="u", model=MODEL)

        page = logger.list_conversations(limit=2, offset=0)
        assert len(page) == 2
        page2 = logger.list_conversations(limit=2, offset=2)
        assert len(page2) == 2
        all_ids = {c["id"] for c in page} | {c["id"] for c in page2}
        assert len(all_ids) == 4  # no overlap
