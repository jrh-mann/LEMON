"""Integration tests for the version-based schema migration runner.

Tests verify that:
- A fresh database receives all migrations and ends at the latest version.
- An existing database at version 0 can be incrementally migrated.
- Running migrations twice is idempotent (no errors, no extra work).
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.backend.storage.migrations import MIGRATIONS, get_schema_version, run_migrations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# The base CREATE TABLE that _init_schema() runs before calling run_migrations.
# NOTE: output_type, is_draft, and all later columns are added by migrations,
# so they are NOT included here (matches version 0 of the schema).
_BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS workflows (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    domain TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    nodes TEXT NOT NULL DEFAULT '[]',
    edges TEXT NOT NULL DEFAULT '[]',
    inputs TEXT NOT NULL DEFAULT '[]',
    outputs TEXT NOT NULL DEFAULT '[]',
    tree TEXT NOT NULL DEFAULT '{}',
    doubts TEXT NOT NULL DEFAULT '[]',
    validation_score INTEGER NOT NULL DEFAULT 0,
    validation_count INTEGER NOT NULL DEFAULT 0,
    is_validated BOOLEAN NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

# Every column that should exist after all migrations have run.
_EXPECTED_COLUMNS = {
    "id",
    "user_id",
    "name",
    "description",
    "domain",
    "tags",
    "nodes",
    "edges",
    "inputs",
    "outputs",
    "tree",
    "doubts",
    "validation_score",
    "validation_count",
    "is_validated",
    "output_type",
    "is_draft",
    "created_at",
    "updated_at",
    # Added by migrations:
    "is_published",
    "review_status",
    "net_votes",
    "published_at",
    "building",
    "build_history",
    "conversation_id",
    "uploaded_files",
}


def _column_names(conn: sqlite3.Connection, table: str = "workflows") -> set:
    """Return the set of column names for *table*."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Return True if *table* exists in the database."""
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row[0] > 0


def _index_exists(conn: sqlite3.Connection, index_name: str) -> bool:
    """Return True if *index_name* exists in the database."""
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name=?",
        (index_name,),
    ).fetchone()
    return row[0] > 0


@pytest.fixture()
def db_conn(tmp_path):
    """Yield a fresh SQLite connection to a temporary database file."""
    db_file = tmp_path / "test_workflows.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFreshDatabase:
    """A brand-new database should receive all migrations end-to-end."""

    def test_fresh_db_all_migrations(self, db_conn):
        """Create the base table then apply all migrations — every expected
        column, index, and auxiliary table must exist afterwards."""
        db_conn.executescript(_BASE_SCHEMA)

        applied = run_migrations(db_conn)

        # All migrations applied
        assert applied == len(MIGRATIONS)

        # Schema version matches the last migration
        assert get_schema_version(db_conn) == MIGRATIONS[-1][0]

        # Every expected column is present
        actual_columns = _column_names(db_conn)
        assert _EXPECTED_COLUMNS.issubset(actual_columns), (
            f"Missing columns: {_EXPECTED_COLUMNS - actual_columns}"
        )

        # workflow_votes table created by migration 8
        assert _table_exists(db_conn, "workflow_votes")

        # Key indexes exist
        for idx in [
            "idx_workflows_is_draft",
            "idx_workflows_is_published",
            "idx_workflows_review_status",
            "idx_votes_workflow",
            "idx_votes_user",
        ]:
            assert _index_exists(db_conn, idx), f"Missing index: {idx}"


class TestIncrementalMigration:
    """An existing database at version 0 should be migrated incrementally."""

    def test_incremental_migration(self, db_conn):
        """Start at version 0 (base table only), apply migrations, then
        verify that new columns are present."""
        db_conn.executescript(_BASE_SCHEMA)

        # Manually set schema version to 0 so we confirm it starts there
        db_conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
        )
        db_conn.execute("INSERT INTO schema_version (version) VALUES (0)")
        db_conn.commit()

        assert get_schema_version(db_conn) == 0

        applied = run_migrations(db_conn)
        assert applied == len(MIGRATIONS)
        assert get_schema_version(db_conn) == MIGRATIONS[-1][0]

        # Spot-check columns added by specific migrations
        cols = _column_names(db_conn)
        assert "is_published" in cols  # migration 3
        assert "building" in cols  # migration 4
        assert "uploaded_files" in cols  # migration 7

    def test_partial_migration(self, db_conn):
        """If the DB is already at version 3, only migrations 4+ run."""
        db_conn.executescript(_BASE_SCHEMA)

        # Manually apply first 3 migrations' column additions
        db_conn.execute(
            "ALTER TABLE workflows ADD COLUMN is_published DEFAULT 0"
        )
        db_conn.execute(
            "ALTER TABLE workflows ADD COLUMN review_status DEFAULT 'unreviewed'"
        )
        db_conn.execute(
            "ALTER TABLE workflows ADD COLUMN net_votes DEFAULT 0"
        )
        db_conn.execute(
            "ALTER TABLE workflows ADD COLUMN published_at DEFAULT NULL"
        )

        # Record version as 3 (first 3 migrations already done)
        db_conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
        )
        db_conn.execute("INSERT INTO schema_version (version) VALUES (3)")
        db_conn.commit()

        applied = run_migrations(db_conn)

        # Only migrations 4-8 should have run
        remaining = [v for v, _, _ in MIGRATIONS if v > 3]
        assert applied == len(remaining)
        assert get_schema_version(db_conn) == MIGRATIONS[-1][0]

        # Columns from later migrations should now exist
        cols = _column_names(db_conn)
        assert "building" in cols
        assert "build_history" in cols
        assert "conversation_id" in cols
        assert "uploaded_files" in cols


class TestIdempotency:
    """Running migrations multiple times must not raise errors."""

    def test_migration_idempotent(self, db_conn):
        """Run migrations twice — second run should apply 0 and not error."""
        db_conn.executescript(_BASE_SCHEMA)

        first_applied = run_migrations(db_conn)
        assert first_applied == len(MIGRATIONS)

        # Second run — everything already applied
        second_applied = run_migrations(db_conn)
        assert second_applied == 0

        # Version unchanged
        assert get_schema_version(db_conn) == MIGRATIONS[-1][0]


class TestWorkflowStoreIntegration:
    """Verify that WorkflowStore._init_schema() uses the migration runner."""

    def test_workflow_store_creates_migrated_schema(self, tmp_path):
        """Instantiating WorkflowStore on a fresh DB should produce a fully
        migrated schema."""
        from src.backend.storage.workflows import WorkflowStore

        store = WorkflowStore(tmp_path / "workflows.db")

        # Open a raw connection to inspect the schema
        conn = sqlite3.connect(str(tmp_path / "workflows.db"))
        try:
            cols = _column_names(conn)
            assert _EXPECTED_COLUMNS.issubset(cols), (
                f"Missing columns: {_EXPECTED_COLUMNS - cols}"
            )
            assert _table_exists(conn, "workflow_votes")
            assert get_schema_version(conn) == MIGRATIONS[-1][0]
        finally:
            conn.close()
