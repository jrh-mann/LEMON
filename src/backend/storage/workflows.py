"""SQLite-backed workflow store for user workflows."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ── Shared SELECT column list used by every query that returns full rows ──
_WORKFLOW_COLUMNS = """
    id, user_id, name, description, domain, tags,
    nodes, edges, inputs, outputs, tree, doubts,
    validation_score, validation_count, is_validated,
    output_type, is_draft, is_published, review_status, net_votes, published_at,
    building, build_history, conversation_id, uploaded_files, created_at, updated_at
"""

# ── Field lists for table-driven update_workflow ──
# Scalar fields are stored as-is (no JSON serialization needed)
_SCALAR_FIELDS = [
    "name", "description", "domain", "validation_score", "validation_count",
    "is_validated", "output_type", "is_draft",
    "building", "conversation_id",
]
# JSON fields require json.dumps() before storage
_JSON_FIELDS = [
    "tags", "nodes", "edges", "inputs", "outputs", "tree", "doubts",
    "build_history", "uploaded_files",
]


@dataclass(frozen=True)
class WorkflowRecord:
    """Represents a stored workflow with metadata."""
    id: str
    user_id: str
    name: str
    description: str
    domain: Optional[str]
    tags: List[str]
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    inputs: List[Dict[str, Any]]
    outputs: List[Dict[str, Any]]
    tree: Dict[str, Any]
    doubts: List[str]
    validation_score: int
    validation_count: int
    is_validated: bool
    created_at: str
    updated_at: str
    output_type: Optional[str] = None  # Type of value workflow returns: string, int, float, bool, json
    is_draft: bool = True  # True = unsaved draft, False = saved to library
    # Legacy DB columns — kept for row_factory compatibility but unused
    is_published: bool = False
    review_status: str = "unreviewed"
    net_votes: int = 0
    published_at: Optional[str] = None
    building: bool = False  # True while a background orchestrator is building this workflow
    build_history: List[Dict[str, str]] = field(default_factory=list)  # Conversation history from the background builder
    conversation_id: Optional[str] = None  # Links to the in-memory ConversationStore for chat history restore
    uploaded_files: List[Dict[str, str]] = field(default_factory=list)  # [{name, rel_path, file_type, purpose}]


class WorkflowStore:
    """Manages workflow persistence in SQLite database."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger("backend.workflows")
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize database schema and apply pending migrations.

        Creates the base ``workflows`` table (version 0) then delegates
        incremental column additions and index creation to the version-based
        migration runner in ``storage.migrations``.
        """
        with self._conn() as conn:
            # Base table — version 0 of the schema.
            # NOTE: output_type, is_draft, and all later columns are added
            # by the migration runner so they are NOT included here.
            conn.executescript(
                """
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

                CREATE INDEX IF NOT EXISTS idx_workflows_user_id
                    ON workflows(user_id);

                CREATE INDEX IF NOT EXISTS idx_workflows_domain
                    ON workflows(domain);

                CREATE INDEX IF NOT EXISTS idx_workflows_created_at
                    ON workflows(created_at DESC);
                """
            )
            # Apply incremental migrations (columns, indexes, auxiliary tables)
            from .migrations import run_migrations

            applied = run_migrations(conn)
            if applied:
                self._logger.info("Applied %d schema migration(s)", applied)

    @contextmanager
    def _conn(self) -> Iterable[sqlite3.Connection]:
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def create_workflow(
        self,
        workflow_id: str,
        user_id: str,
        name: str,
        description: str,
        *,
        domain: Optional[str] = None,
        tags: Optional[List[str]] = None,
        nodes: Optional[List[Dict[str, Any]]] = None,
        edges: Optional[List[Dict[str, Any]]] = None,
        inputs: Optional[List[Dict[str, Any]]] = None,
        outputs: Optional[List[Dict[str, Any]]] = None,
        tree: Optional[Dict[str, Any]] = None,
        doubts: Optional[List[str]] = None,
        validation_score: int = 0,
        validation_count: int = 0,
        is_validated: bool = False,
        output_type: Optional[str] = None,
        is_draft: bool = True,
        is_published: bool = False,
        building: bool = False,
        build_history: Optional[List[Dict[str, str]]] = None,
    ) -> None:
        """Create a new workflow in the database.

        Args:
            workflow_id: Unique workflow identifier
            user_id: Owner user ID
            name: Workflow name
            description: Workflow description
            domain: Optional domain classification
            tags: List of tags for categorization
            nodes: Flowchart nodes (frontend format)
            edges: Flowchart edges (frontend format)
            inputs: Workflow input definitions
            outputs: Workflow output definitions
            tree: Workflow tree structure
            doubts: List of validation doubts/concerns
            validation_score: Number of successful validations
            validation_count: Total validation attempts
            is_validated: Whether workflow passed validation
            output_type: Type of value workflow returns (string, int, float, bool, json)
            is_draft: True for unsaved drafts, False for saved to library
            is_published: True to publish to community library for peer review
        """
        now = datetime.now(timezone.utc).isoformat()

        # Serialize lists/dicts to JSON
        tags_json = json.dumps(tags or [])
        nodes_json = json.dumps(nodes or [])
        edges_json = json.dumps(edges or [])
        inputs_json = json.dumps(inputs or [])
        outputs_json = json.dumps(outputs or [])
        tree_json = json.dumps(tree or {})
        doubts_json = json.dumps(doubts or [])
        build_history_json = json.dumps(build_history or [])

        # Set published_at if publishing
        published_at = now if is_published else None

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO workflows (
                    id, user_id, name, description, domain, tags,
                    nodes, edges, inputs, outputs, tree, doubts,
                    validation_score, validation_count, is_validated,
                    output_type, is_draft, is_published, review_status, net_votes, published_at,
                    building, build_history, conversation_id, uploaded_files, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workflow_id, user_id, name, description, domain, tags_json,
                    nodes_json, edges_json, inputs_json, outputs_json, tree_json, doubts_json,
                    validation_score, validation_count, is_validated,
                    output_type or "string", is_draft, is_published, "unreviewed", 0, published_at,
                    building, build_history_json, None, "[]", now, now
                ),
            )
        self._logger.info("Created workflow id=%s user=%s name=%s is_published=%s", workflow_id, user_id, name, is_published)

    def get_workflow(self, workflow_id: str, user_id: str) -> Optional[WorkflowRecord]:
        """Get a workflow by ID, ensuring it belongs to the user."""
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT {_WORKFLOW_COLUMNS} FROM workflows WHERE id = ? AND user_id = ?",
                (workflow_id, user_id),
            ).fetchone()

        return self._row_to_workflow(row) if row else None

    def update_workflow(
        self,
        workflow_id: str,
        user_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        domain: Optional[str] = None,
        tags: Optional[List[str]] = None,
        nodes: Optional[List[Dict[str, Any]]] = None,
        edges: Optional[List[Dict[str, Any]]] = None,
        inputs: Optional[List[Dict[str, Any]]] = None,
        outputs: Optional[List[Dict[str, Any]]] = None,
        tree: Optional[Dict[str, Any]] = None,
        doubts: Optional[List[str]] = None,
        validation_score: Optional[int] = None,
        validation_count: Optional[int] = None,
        is_validated: Optional[bool] = None,
        output_type: Optional[str] = None,
        is_draft: Optional[bool] = None,
        is_published: Optional[bool] = None,
        review_status: Optional[str] = None,
        net_votes: Optional[int] = None,
        building: Optional[bool] = None,
        build_history: Optional[List[Dict[str, str]]] = None,
        conversation_id: Optional[str] = None,
        uploaded_files: Optional[List[Dict[str, str]]] = None,
    ) -> bool:
        """Update an existing workflow. Only provided (non-None) fields are written."""
        # Collect all kwargs into a dict so we can iterate the field lists
        kwargs: Dict[str, Any] = {
            "name": name, "description": description, "domain": domain,
            "tags": tags, "nodes": nodes, "edges": edges,
            "inputs": inputs, "outputs": outputs, "tree": tree,
            "doubts": doubts, "validation_score": validation_score,
            "validation_count": validation_count, "is_validated": is_validated,
            "output_type": output_type, "is_draft": is_draft,
            "is_published": is_published, "review_status": review_status,
            "net_votes": net_votes, "building": building,
            "build_history": build_history, "conversation_id": conversation_id,
            "uploaded_files": uploaded_files,
        }

        updates: List[str] = []
        params: List[Any] = []

        # Scalar fields — stored as-is
        for field_name in _SCALAR_FIELDS:
            if kwargs[field_name] is not None:
                updates.append(f"{field_name} = ?")
                params.append(kwargs[field_name])

        # JSON fields — need json.dumps() before storage
        for field_name in _JSON_FIELDS:
            if kwargs[field_name] is not None:
                updates.append(f"{field_name} = ?")
                params.append(json.dumps(kwargs[field_name]))

        # is_published needs special handling: set published_at on first publish
        if is_published is not None:
            updates.append("is_published = ?")
            params.append(is_published)
            if is_published:
                # COALESCE preserves the original published_at if already set
                updates.append("published_at = COALESCE(published_at, ?)")
                params.append(datetime.now(timezone.utc).isoformat())

        if not updates:
            return True  # No updates requested

        # Always update updated_at timestamp
        updates.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())

        # WHERE clause params
        params.extend([workflow_id, user_id])

        query = f"UPDATE workflows SET {', '.join(updates)} WHERE id = ? AND user_id = ?"

        with self._conn() as conn:
            result = conn.execute(query, params)
            rows_affected = result.rowcount

        if rows_affected > 0:
            self._logger.info("Updated workflow id=%s user=%s", workflow_id, user_id)
            return True

        self._logger.warning("Failed to update workflow id=%s user=%s (not found or unauthorized)", workflow_id, user_id)
        return False

    def try_set_building(self, workflow_id: str, user_id: str) -> bool:
        """Atomically set building=True only if currently building=False.

        Uses a single SQL UPDATE with a WHERE guard so that concurrent callers
        cannot both succeed — only one wins the race (rowcount == 1).

        Returns True if the flag was set (caller won), False if already building.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE workflows SET building = 1, updated_at = ? "
                "WHERE id = ? AND user_id = ? AND building = 0",
                (now, workflow_id, user_id),
            )
            won = cursor.rowcount == 1
        if won:
            self._logger.info("Atomically set building=True for workflow %s", workflow_id)
        else:
            self._logger.info("Workflow %s already building — atomic set failed", workflow_id)
        return won

    def clear_stale_building_flags(self) -> int:
        """Reset building=True flags left by dead threads after server restart.

        Called once at startup. Any workflow still marked building=True has a
        dead builder thread (daemon threads don't survive restarts).

        Returns:
            Number of workflows whose building flag was cleared.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE workflows SET building = 0, updated_at = ? WHERE building = 1",
                (now,),
            )
            count = cursor.rowcount
        if count:
            self._logger.warning(
                "Cleared stale building flag on %d workflow(s) from previous server run", count,
            )
        return count

    def delete_workflow(self, workflow_id: str, user_id: str) -> bool:
        """Delete a workflow owned by user_id. Returns True if deleted."""
        with self._conn() as conn:
            result = conn.execute(
                "DELETE FROM workflows WHERE id = ? AND user_id = ?",
                (workflow_id, user_id),
            )
            rows_affected = result.rowcount

        if rows_affected > 0:
            self._logger.info("Deleted workflow id=%s user=%s", workflow_id, user_id)
            return True

        self._logger.warning("Failed to delete workflow id=%s user=%s (not found or unauthorized)", workflow_id, user_id)
        return False

    def list_workflows(
        self,
        user_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[WorkflowRecord], int]:
        """List workflows for a user, paginated, ordered by most recently updated."""
        with self._conn() as conn:
            count_row = conn.execute(
                "SELECT COUNT(*) FROM workflows WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            total_count = count_row[0] if count_row else 0

            rows = conn.execute(
                f"""
                SELECT {_WORKFLOW_COLUMNS}
                FROM workflows
                WHERE user_id = ?
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (user_id, limit, offset),
            ).fetchall()

        workflows = [self._row_to_workflow(row) for row in rows if row]
        return workflows, total_count

    def search_workflows(
        self,
        user_id: str,
        *,
        query: Optional[str] = None,
        domain: Optional[str] = None,
        validated: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[WorkflowRecord], int]:
        """Search workflows with optional text, domain, and validation filters."""
        where_clauses = ["user_id = ?"]
        params: List[Any] = [user_id]

        if query:
            where_clauses.append("(name LIKE ? OR description LIKE ?)")
            search_term = f"%{query}%"
            params.extend([search_term, search_term])

        if domain:
            where_clauses.append("domain = ?")
            params.append(domain)

        if validated is not None:
            where_clauses.append("is_validated = ?")
            params.append(validated)

        where_sql = " AND ".join(where_clauses)

        with self._conn() as conn:
            count_row = conn.execute(
                f"SELECT COUNT(*) FROM workflows WHERE {where_sql}",
                params,
            ).fetchone()
            total_count = count_row[0] if count_row else 0

            rows = conn.execute(
                f"""
                SELECT {_WORKFLOW_COLUMNS}
                FROM workflows
                WHERE {where_sql}
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            ).fetchall()

        workflows = [self._row_to_workflow(row) for row in rows if row]
        return workflows, total_count

    def get_domains(self, user_id: str) -> List[str]:
        """Return distinct non-null domain strings for a user's workflows."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT domain
                FROM workflows
                WHERE user_id = ? AND domain IS NOT NULL
                ORDER BY domain
                """,
                (user_id,),
            ).fetchall()

        return [row[0] for row in rows if row[0]]

    @staticmethod
    def _row_to_workflow(row: Optional[sqlite3.Row]) -> Optional[WorkflowRecord]:
        """Convert a SQLite row to a WorkflowRecord, or None if invalid."""
        if not row:
            return None

        try:
            return WorkflowRecord(
                id=row["id"],
                user_id=row["user_id"],
                name=row["name"],
                description=row["description"],
                domain=row["domain"],
                tags=json.loads(row["tags"]),
                nodes=json.loads(row["nodes"]),
                edges=json.loads(row["edges"]),
                inputs=json.loads(row["inputs"]),
                outputs=json.loads(row["outputs"]),
                tree=json.loads(row["tree"]),
                doubts=json.loads(row["doubts"]),
                validation_score=row["validation_score"],
                validation_count=row["validation_count"],
                is_validated=bool(row["is_validated"]),
                output_type=row["output_type"],
                is_draft=bool(row["is_draft"]),
                is_published=bool(row["is_published"]) if row["is_published"] is not None else False,
                review_status=row["review_status"] or "unreviewed",
                net_votes=row["net_votes"] or 0,
                published_at=row["published_at"],
                building=bool(row["building"]) if row["building"] is not None else False,
                build_history=json.loads(row["build_history"]) if row["build_history"] else [],
                conversation_id=row["conversation_id"] if "conversation_id" in row.keys() else None,
                uploaded_files=json.loads(row["uploaded_files"]) if "uploaded_files" in row.keys() and row["uploaded_files"] else [],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            row_id = "unknown"
            if row is not None and "id" in row.keys():
                row_id = row["id"]
            logging.getLogger("backend.workflows").error(
                "Failed to deserialize workflow row id=%s: %s",
                row_id,
                e,
            )
            return None
