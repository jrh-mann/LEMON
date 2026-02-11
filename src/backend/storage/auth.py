"""SQLite-backed auth store for users and sessions."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Tuple


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str
    name: str
    password_hash: str
    created_at: str
    last_login_at: Optional[str]


@dataclass(frozen=True)
class AuthSession:
    id: str
    user_id: str
    token_hash: str
    created_at: str
    expires_at: str
    last_used_at: str


@dataclass(frozen=True)
class Integration:
    """External service integration credentials."""

    id: str
    user_id: str
    service: str  # e.g., "miro", "figma"
    access_token: str
    refresh_token: Optional[str]
    expires_at: Optional[str]  # ISO format timestamp
    created_at: str
    updated_at: str


class AuthStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger("backend.auth")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_login_at TEXT
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_token_hash
                    ON sessions(token_hash);

                CREATE INDEX IF NOT EXISTS idx_sessions_user_id
                    ON sessions(user_id);

                CREATE TABLE IF NOT EXISTS integrations (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    service TEXT NOT NULL,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT,
                    expires_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    UNIQUE(user_id, service)
                );

                CREATE INDEX IF NOT EXISTS idx_integrations_user_service
                    ON integrations(user_id, service);
                """
            )

    @contextmanager
    def _conn(self) -> Iterable[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def create_user(self, user_id: str, email: str, name: str, password_hash: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO users (id, email, name, password_hash, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, email, name, password_hash, now),
            )
        self._logger.info("Created user id=%s email=%s", user_id, email)

    def get_user_by_email(self, email: str) -> Optional[AuthUser]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, email, name, password_hash, created_at, last_login_at
                FROM users
                WHERE email = ?
                """,
                (email,),
            ).fetchone()
        return self._row_to_user(row)

    def get_user_by_id(self, user_id: str) -> Optional[AuthUser]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, email, name, password_hash, created_at, last_login_at
                FROM users
                WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
        return self._row_to_user(row)

    def update_last_login(self, user_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE users SET last_login_at = ? WHERE id = ?",
                (now, user_id),
            )

    def create_session(
        self,
        session_id: str,
        user_id: str,
        token_hash: str,
        *,
        expires_at: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, user_id, token_hash, created_at, expires_at, last_used_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, user_id, token_hash, now, expires_at, now),
            )

    def get_session_by_token_hash(
        self,
        token_hash: str,
    ) -> Optional[Tuple[AuthSession, AuthUser]]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT
                    sessions.id AS session_id,
                    sessions.user_id AS session_user_id,
                    sessions.token_hash,
                    sessions.created_at AS session_created_at,
                    sessions.expires_at,
                    sessions.last_used_at,
                    users.id AS user_id,
                    users.email,
                    users.name,
                    users.password_hash,
                    users.created_at AS user_created_at,
                    users.last_login_at
                FROM sessions
                JOIN users ON sessions.user_id = users.id
                WHERE sessions.token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
        if not row:
            return None
        session = AuthSession(
            id=row["session_id"],
            user_id=row["session_user_id"],
            token_hash=row["token_hash"],
            created_at=row["session_created_at"],
            expires_at=row["expires_at"],
            last_used_at=row["last_used_at"],
        )
        user = AuthUser(
            id=row["user_id"],
            email=row["email"],
            name=row["name"],
            password_hash=row["password_hash"],
            created_at=row["user_created_at"],
            last_login_at=row["last_login_at"],
        )
        return session, user

    def touch_session(self, session_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE sessions SET last_used_at = ? WHERE id = ?",
                (now, session_id),
            )

    def delete_session_by_token_hash(self, token_hash: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                (token_hash,),
            )

    def delete_expired_sessions(self) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            result = conn.execute(
                "DELETE FROM sessions WHERE expires_at <= ?",
                (now,),
            )
        return result.rowcount if result else 0

    def prune_sessions(self, user_id: str, *, max_sessions: int) -> int:
        if max_sessions <= 0:
            return 0
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id
                FROM sessions
                WHERE user_id = ?
                ORDER BY last_used_at DESC
                """,
                (user_id,),
            ).fetchall()
            if len(rows) <= max_sessions:
                return 0
            ids_to_delete = [row["id"] for row in rows[max_sessions:]]
            conn.executemany(
                "DELETE FROM sessions WHERE id = ?",
                [(session_id,) for session_id in ids_to_delete],
            )
        return len(ids_to_delete)

    @staticmethod
    def _row_to_user(row: Optional[sqlite3.Row]) -> Optional[AuthUser]:
        if not row:
            return None
        return AuthUser(
            id=row["id"],
            email=row["email"],
            name=row["name"],
            password_hash=row["password_hash"],
            created_at=row["created_at"],
            last_login_at=row["last_login_at"],
        )

    # =========================================================================
    # INTEGRATION TOKEN MANAGEMENT
    # =========================================================================

    def set_integration_token(
        self,
        user_id: str,
        service: str,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_at: Optional[str] = None,
    ) -> Integration:
        """Store or update an integration token for a user.

        Args:
            user_id: The user's ID
            service: Service name (e.g., "miro")
            access_token: The access token to store
            refresh_token: Optional refresh token for OAuth
            expires_at: Optional expiration timestamp (ISO format)

        Returns:
            The Integration object
        """
        now = datetime.now(timezone.utc).isoformat()
        integration_id = f"int_{service}_{user_id}"

        with self._conn() as conn:
            # Upsert: insert or update if exists
            conn.execute(
                """
                INSERT INTO integrations (id, user_id, service, access_token, refresh_token, expires_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, service) DO UPDATE SET
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    expires_at = excluded.expires_at,
                    updated_at = excluded.updated_at
                """,
                (integration_id, user_id, service, access_token, refresh_token, expires_at, now, now),
            )

        self._logger.info("Set integration token for user=%s service=%s", user_id, service)
        return Integration(
            id=integration_id,
            user_id=user_id,
            service=service,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )

    def get_integration_token(self, user_id: str, service: str) -> Optional[Integration]:
        """Get an integration token for a user.

        Args:
            user_id: The user's ID
            service: Service name (e.g., "miro")

        Returns:
            Integration object if found, None otherwise
        """
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, user_id, service, access_token, refresh_token, expires_at, created_at, updated_at
                FROM integrations
                WHERE user_id = ? AND service = ?
                """,
                (user_id, service),
            ).fetchone()

        if not row:
            return None

        return Integration(
            id=row["id"],
            user_id=row["user_id"],
            service=row["service"],
            access_token=row["access_token"],
            refresh_token=row["refresh_token"],
            expires_at=row["expires_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def delete_integration_token(self, user_id: str, service: str) -> bool:
        """Delete an integration token for a user.

        Args:
            user_id: The user's ID
            service: Service name (e.g., "miro")

        Returns:
            True if deleted, False if not found
        """
        with self._conn() as conn:
            result = conn.execute(
                """
                DELETE FROM integrations
                WHERE user_id = ? AND service = ?
                """,
                (user_id, service),
            )

        deleted = result.rowcount > 0 if result else False
        if deleted:
            self._logger.info("Deleted integration token for user=%s service=%s", user_id, service)
        return deleted

    def has_integration(self, user_id: str, service: str) -> bool:
        """Check if a user has an integration token.

        Args:
            user_id: The user's ID
            service: Service name (e.g., "miro")

        Returns:
            True if token exists, False otherwise
        """
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM integrations
                WHERE user_id = ? AND service = ?
                """,
                (user_id, service),
            ).fetchone()

        return row is not None
