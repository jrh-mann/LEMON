"""Version-based schema migration runner for SQLite databases.

Tracks applied migrations in a ``schema_version`` table and applies only
those that haven't been run yet.  Each migration entry is a
(version, description, sql) tuple.  Migrations are applied in order; each
SQL string may contain multiple statements (executed via ``executescript``).
"""

import sqlite3
import logging
from typing import List, Tuple

logger = logging.getLogger("backend.storage")

# ---------------------------------------------------------------------------
# Migration registry
# ---------------------------------------------------------------------------
# Each migration is (version, description, sql).
# Migrations are applied in ascending version order.  A fresh database starts
# at version 0 (base CREATE TABLE) and runs all of them in sequence.  An
# existing database skips those already applied.
#
# IMPORTANT: never reorder or delete an existing entry.  Only append new ones
# with an incremented version number.
# ---------------------------------------------------------------------------
MIGRATIONS: List[Tuple[int, str, str]] = [
    # --- columns added after the original CREATE TABLE -----------------------
    (
        1,
        "Add output_type column",
        "ALTER TABLE workflows ADD COLUMN output_type TEXT DEFAULT 'string';",
    ),
    (
        2,
        "Add is_draft column with index",
        (
            "ALTER TABLE workflows ADD COLUMN is_draft BOOLEAN NOT NULL DEFAULT 0;\n"
            "CREATE INDEX IF NOT EXISTS idx_workflows_is_draft ON workflows(is_draft);"
        ),
    ),
    (
        3,
        "Add peer-review columns (is_published, review_status, net_votes, published_at)",
        (
            "ALTER TABLE workflows ADD COLUMN is_published DEFAULT 0;\n"
            "ALTER TABLE workflows ADD COLUMN review_status DEFAULT 'unreviewed';\n"
            "ALTER TABLE workflows ADD COLUMN net_votes DEFAULT 0;\n"
            "ALTER TABLE workflows ADD COLUMN published_at DEFAULT NULL;"
        ),
    ),
    (
        4,
        "Add building flag column",
        "ALTER TABLE workflows ADD COLUMN building BOOLEAN NOT NULL DEFAULT 0;",
    ),
    (
        5,
        "Add build_history column",
        "ALTER TABLE workflows ADD COLUMN build_history TEXT NOT NULL DEFAULT '[]';",
    ),
    (
        6,
        "Add conversation_id column",
        "ALTER TABLE workflows ADD COLUMN conversation_id TEXT;",
    ),
    (
        7,
        "Add uploaded_files column",
        "ALTER TABLE workflows ADD COLUMN uploaded_files TEXT NOT NULL DEFAULT '[]';",
    ),
    # --- indexes & auxiliary tables ------------------------------------------
    (
        8,
        "Add peer-review indexes and workflow_votes table",
        (
            "CREATE INDEX IF NOT EXISTS idx_workflows_is_published ON workflows(is_published);\n"
            "CREATE INDEX IF NOT EXISTS idx_workflows_review_status ON workflows(review_status);\n"
            "CREATE TABLE IF NOT EXISTS workflow_votes (\n"
            "    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    workflow_id TEXT NOT NULL,\n"
            "    user_id TEXT NOT NULL,\n"
            "    vote INTEGER NOT NULL CHECK (vote IN (-1, 1)),\n"
            "    created_at TEXT NOT NULL,\n"
            "    UNIQUE(workflow_id, user_id),\n"
            "    FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE\n"
            ");\n"
            "CREATE INDEX IF NOT EXISTS idx_votes_workflow ON workflow_votes(workflow_id);\n"
            "CREATE INDEX IF NOT EXISTS idx_votes_user ON workflow_votes(user_id);"
        ),
    ),
]


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_schema_version(conn: sqlite3.Connection) -> int:
    """Return the current schema version, creating the tracking table if needed."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
    )
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (0)")
        conn.commit()
        return 0
    # row may be a sqlite3.Row or plain tuple depending on row_factory
    return row[0] if isinstance(row, (tuple, list)) else row["version"]


def run_migrations(conn: sqlite3.Connection) -> int:
    """Apply all pending migrations and return the number applied."""
    current = get_schema_version(conn)
    applied = 0

    for version, description, sql in MIGRATIONS:
        if version <= current:
            continue
        logger.info("Applying migration %d: %s", version, description)
        conn.executescript(sql)
        conn.execute("UPDATE schema_version SET version = ?", (version,))
        conn.commit()
        applied += 1
        logger.info("Migration %d applied successfully", version)

    return applied
