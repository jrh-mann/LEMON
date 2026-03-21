"""Persistent SQLite audit log for LLM conversations.

Captures the full conversation lifecycle — messages, tool calls, thinking,
compaction events, errors, and workflow snapshots — so that LLM performance
can be evaluated after the fact.

Follows the same patterns as WorkflowStore: one connection per operation via
a ``_conn()`` context manager, WAL mode for concurrent reads/writes, and
thread-safe sequence numbering.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


_log = logging.getLogger(__name__)


class ConversationLogger:
    """Write-heavy audit log backed by a single SQLite file."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        # Per-conversation monotonic sequence counters.
        self._seq_counters: Dict[str, int] = {}
        self._seq_lock = threading.Lock()
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """Yield a short-lived connection with Row factory."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        """Create tables if they don't exist and enable WAL mode."""
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id          TEXT PRIMARY KEY,
                    workflow_id TEXT,
                    user_id     TEXT NOT NULL,
                    model       TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS entries (
                    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id       TEXT NOT NULL REFERENCES conversations(id),
                    seq                   INTEGER NOT NULL,
                    entry_type            TEXT NOT NULL,
                    role                  TEXT,
                    content               TEXT,
                    tool_name             TEXT,
                    tool_arguments        TEXT,
                    tool_result           TEXT,
                    tool_success          INTEGER,
                    tool_duration_ms      REAL,
                    input_tokens          INTEGER,
                    output_tokens         INTEGER,
                    cache_creation_tokens INTEGER,
                    cache_read_tokens     INTEGER,
                    workflow_snapshot      TEXT,
                    files                 TEXT,
                    task_id               TEXT,
                    timestamp             TEXT NOT NULL,
                    UNIQUE(conversation_id, seq)
                );
                """
            )

    # ------------------------------------------------------------------
    # Sequence numbering
    # ------------------------------------------------------------------

    def _next_seq(self, conversation_id: str) -> int:
        """Return the next monotonic sequence number for *conversation_id*.

        Thread-safe.  On first access for a conversation the counter is
        seeded from the database so that restarts don't reset numbering.
        """
        with self._seq_lock:
            if conversation_id not in self._seq_counters:
                # Seed from DB.
                with self._conn() as conn:
                    row = conn.execute(
                        "SELECT COALESCE(MAX(seq), 0) AS m "
                        "FROM entries WHERE conversation_id = ?",
                        (conversation_id,),
                    ).fetchone()
                    self._seq_counters[conversation_id] = row["m"]
            self._seq_counters[conversation_id] += 1
            return self._seq_counters[conversation_id]

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def ensure_conversation(
        self,
        conversation_id: str,
        *,
        user_id: str,
        workflow_id: Optional[str] = None,
        model: str,
    ) -> None:
        """Idempotent INSERT OR IGNORE — safe to call on every request."""
        now = self._now()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO conversations
                    (id, workflow_id, user_id, model, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (conversation_id, workflow_id, user_id, model, now, now),
            )
            # Always bump updated_at so repeated calls track activity.
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )

    def _insert_entry(
        self,
        conversation_id: str,
        entry_type: str,
        **cols: Any,
    ) -> int:
        """Low-level helper that inserts one entry row and returns its seq."""
        seq = self._next_seq(conversation_id)
        now = self._now()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO entries
                    (conversation_id, seq, entry_type,
                     role, content, tool_name, tool_arguments, tool_result,
                     tool_success, tool_duration_ms,
                     input_tokens, output_tokens,
                     cache_creation_tokens, cache_read_tokens,
                     workflow_snapshot, files, task_id, timestamp)
                VALUES (?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?,
                        ?, ?,
                        ?, ?,
                        ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    seq,
                    entry_type,
                    cols.get("role"),
                    cols.get("content"),
                    cols.get("tool_name"),
                    cols.get("tool_arguments"),
                    cols.get("tool_result"),
                    cols.get("tool_success"),
                    cols.get("tool_duration_ms"),
                    cols.get("input_tokens"),
                    cols.get("output_tokens"),
                    cols.get("cache_creation_tokens"),
                    cols.get("cache_read_tokens"),
                    cols.get("workflow_snapshot"),
                    cols.get("files"),
                    cols.get("task_id"),
                    now,
                ),
            )
        return seq

    # -- Convenience writers ------------------------------------------------

    def log_user_message(
        self,
        conversation_id: str,
        content: str,
        *,
        files: Optional[List[Dict[str, Any]]] = None,
        task_id: Optional[str] = None,
    ) -> int:
        return self._insert_entry(
            conversation_id,
            "user_message",
            role="user",
            content=content,
            files=json.dumps(files) if files else None,
            task_id=task_id,
        )

    def log_assistant_response(
        self,
        conversation_id: str,
        content: str,
        *,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        cache_creation_tokens: Optional[int] = None,
        cache_read_tokens: Optional[int] = None,
        task_id: Optional[str] = None,
    ) -> int:
        return self._insert_entry(
            conversation_id,
            "assistant_response",
            role="assistant",
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
            task_id=task_id,
        )

    def log_tool_call(
        self,
        conversation_id: str,
        tool_name: str,
        arguments: Any,
        result: Any,
        success: bool,
        duration_ms: float,
        *,
        task_id: Optional[str] = None,
    ) -> int:
        return self._insert_entry(
            conversation_id,
            "tool_call",
            tool_name=tool_name,
            tool_arguments=json.dumps(arguments, default=str),
            tool_result=json.dumps(result, default=str),
            tool_success=1 if success else 0,
            tool_duration_ms=duration_ms,
            task_id=task_id,
        )

    def log_thinking(
        self,
        conversation_id: str,
        content: str,
        *,
        task_id: Optional[str] = None,
    ) -> int:
        return self._insert_entry(
            conversation_id,
            "thinking",
            content=content,
            task_id=task_id,
        )

    def log_compaction(
        self,
        conversation_id: str,
        original_count: int,
        summary: str,
        discarded_messages: Any,
    ) -> int:
        """Record a history compaction event.

        *discarded_messages* is the list of messages that were dropped;
        stored as JSON in the ``content`` column so they can be inspected
        later.
        """
        payload = {
            "original_count": original_count,
            "summary": summary,
            "discarded_messages": discarded_messages,
        }
        return self._insert_entry(
            conversation_id,
            "compaction",
            content=json.dumps(payload, default=str),
        )

    def log_workflow_snapshot(
        self,
        conversation_id: str,
        workflow: Dict[str, Any],
        *,
        task_id: Optional[str] = None,
    ) -> int:
        return self._insert_entry(
            conversation_id,
            "workflow_snapshot",
            workflow_snapshot=json.dumps(workflow, default=str),
            task_id=task_id,
        )

    def log_error(
        self,
        conversation_id: str,
        error: Any,
        *,
        task_id: Optional[str] = None,
    ) -> int:
        return self._insert_entry(
            conversation_id,
            "error",
            content=str(error),
            task_id=task_id,
        )

    # ------------------------------------------------------------------
    # Read API (for eval tooling)
    # ------------------------------------------------------------------

    def get_conversation_timeline(
        self,
        conversation_id: str,
        *,
        entry_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Return entries for a conversation, ordered by seq.

        Optionally filter to specific *entry_types*.
        """
        with self._conn() as conn:
            if entry_types:
                placeholders = ",".join("?" for _ in entry_types)
                rows = conn.execute(
                    f"SELECT * FROM entries "
                    f"WHERE conversation_id = ? AND entry_type IN ({placeholders}) "
                    f"ORDER BY seq",
                    [conversation_id, *entry_types],
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM entries WHERE conversation_id = ? ORDER BY seq",
                    (conversation_id,),
                ).fetchall()
        return [dict(r) for r in rows]

    def list_conversations(
        self,
        *,
        user_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List conversations with optional filters, newest first."""
        clauses: List[str] = []
        params: List[Any] = []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if workflow_id is not None:
            clauses.append("workflow_id = ?")
            params.append(workflow_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params += [limit, offset]
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM conversations {where} "
                f"ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def get_tool_call_stats(
        self,
        *,
        conversation_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Aggregate tool call stats, optionally scoped to one conversation."""
        where = ""
        params: List[Any] = []
        if conversation_id:
            where = "AND conversation_id = ?"
            params.append(conversation_id)
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT tool_name,
                       COUNT(*)                        AS call_count,
                       SUM(tool_success)               AS success_count,
                       COUNT(*) - SUM(tool_success)    AS failure_count,
                       AVG(tool_duration_ms)            AS avg_duration_ms,
                       SUM(tool_duration_ms)            AS total_duration_ms
                FROM entries
                WHERE entry_type = 'tool_call' {where}
                GROUP BY tool_name
                ORDER BY call_count DESC
                """,
                params,
            ).fetchall()
        return [dict(r) for r in rows]
