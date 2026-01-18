"""SQLite-backed history store for subagent conversations."""

from __future__ import annotations

import logging
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class Message:
    role: str
    content: str


class HistoryStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._logger = logging.getLogger("backend.history")

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    image_name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );
                """
            )

    @contextmanager
    def _conn(self) -> Iterable[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def create_session(self, session_id: str, image_name: str) -> None:
        self._logger.debug("Creating session id=%s image=%s", session_id, image_name)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO sessions (id, image_name, created_at) VALUES (?, ?, ?)",
                (session_id, image_name, datetime.now(timezone.utc).isoformat()),
            )

    def get_session_image(self, session_id: str) -> Optional[str]:
        self._logger.debug("Fetching session image id=%s", session_id)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT image_name FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            return row[0] if row else None

    def add_message(self, session_id: str, role: str, content: str) -> None:
        self._logger.debug(
            "Adding message session_id=%s role=%s bytes=%d",
            session_id,
            role,
            len(content.encode("utf-8")),
        )
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (session_id, role, content, datetime.now(timezone.utc).isoformat()),
            )

    def store_analysis(self, session_id: str, analysis: dict) -> None:
        payload = json.dumps(analysis, ensure_ascii=True)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO analyses (session_id, analysis_json, created_at) VALUES (?, ?, ?)",
                (session_id, payload, datetime.now(timezone.utc).isoformat()),
            )

    def get_latest_analysis(self) -> Optional[Tuple[str, dict]]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT session_id, analysis_json
                FROM analyses
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
        if not row:
            return None
        session_id, payload = row
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            self._logger.warning("Failed to decode analysis_json for session_id=%s", session_id)
            return None
        if not isinstance(data, dict):
            return None
        return session_id, data

    def list_messages(self, session_id: str, limit: int = 20) -> List[Message]:
        self._logger.debug("Listing messages session_id=%s limit=%s", session_id, limit)
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT role, content
                FROM messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()
        messages = [Message(role=row[0], content=row[1]) for row in rows]
        if limit and len(messages) > limit:
            return messages[-limit:]
        return messages
