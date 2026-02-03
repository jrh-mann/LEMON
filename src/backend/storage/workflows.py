"""SQLite-backed workflow store for user workflows."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


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


class WorkflowStore:
    """Manages workflow persistence in SQLite database."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger("backend.workflows")
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize database schema for workflows."""
        with self._conn() as conn:
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
                    output_type TEXT DEFAULT 'string',
                    is_draft BOOLEAN NOT NULL DEFAULT 1,
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
            # Add output_type column if it doesn't exist (migration for existing DBs)
            try:
                conn.execute("SELECT output_type FROM workflows LIMIT 1")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE workflows ADD COLUMN output_type TEXT DEFAULT 'string'")
            # Add is_draft column if it doesn't exist (migration for existing DBs)
            try:
                conn.execute("SELECT is_draft FROM workflows LIMIT 1")
            except sqlite3.OperationalError:
                # Default existing workflows to is_draft=0 (saved) since they were manually saved
                conn.execute("ALTER TABLE workflows ADD COLUMN is_draft BOOLEAN NOT NULL DEFAULT 0")
            # Create is_draft index after migration ensures column exists
            conn.execute("CREATE INDEX IF NOT EXISTS idx_workflows_is_draft ON workflows(is_draft)")

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

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO workflows (
                    id, user_id, name, description, domain, tags,
                    nodes, edges, inputs, outputs, tree, doubts,
                    validation_score, validation_count, is_validated,
                    output_type, is_draft, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workflow_id, user_id, name, description, domain, tags_json,
                    nodes_json, edges_json, inputs_json, outputs_json, tree_json, doubts_json,
                    validation_score, validation_count, is_validated,
                    output_type or "string", is_draft, now, now
                ),
            )
        self._logger.info("Created workflow id=%s user=%s name=%s is_draft=%s", workflow_id, user_id, name, is_draft)

    def get_workflow(self, workflow_id: str, user_id: str) -> Optional[WorkflowRecord]:
        """Get a workflow by ID, ensuring it belongs to the user.

        Args:
            workflow_id: Workflow identifier
            user_id: User ID to verify ownership

        Returns:
            WorkflowRecord if found and owned by user, None otherwise
        """
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, user_id, name, description, domain, tags,
                       nodes, edges, inputs, outputs, tree, doubts,
                       validation_score, validation_count, is_validated,
                       output_type, is_draft, created_at, updated_at
                FROM workflows
                WHERE id = ? AND user_id = ?
                """,
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
    ) -> bool:
        """Update an existing workflow.

        Args:
            workflow_id: Workflow identifier
            user_id: User ID to verify ownership
            **kwargs: Fields to update (only provided fields are updated)

        Returns:
            True if workflow was updated, False if not found/unauthorized
        """
        # Build dynamic UPDATE query for provided fields
        updates = []
        params: List[Any] = []

        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if domain is not None:
            updates.append("domain = ?")
            params.append(domain)
        if tags is not None:
            updates.append("tags = ?")
            params.append(json.dumps(tags))
        if nodes is not None:
            updates.append("nodes = ?")
            params.append(json.dumps(nodes))
        if edges is not None:
            updates.append("edges = ?")
            params.append(json.dumps(edges))
        if inputs is not None:
            updates.append("inputs = ?")
            params.append(json.dumps(inputs))
        if outputs is not None:
            updates.append("outputs = ?")
            params.append(json.dumps(outputs))
        if tree is not None:
            updates.append("tree = ?")
            params.append(json.dumps(tree))
        if doubts is not None:
            updates.append("doubts = ?")
            params.append(json.dumps(doubts))
        if validation_score is not None:
            updates.append("validation_score = ?")
            params.append(validation_score)
        if validation_count is not None:
            updates.append("validation_count = ?")
            params.append(validation_count)
        if is_validated is not None:
            updates.append("is_validated = ?")
            params.append(is_validated)
        if output_type is not None:
            updates.append("output_type = ?")
            params.append(output_type)
        if is_draft is not None:
            updates.append("is_draft = ?")
            params.append(is_draft)

        if not updates:
            return True  # No updates requested

        # Always update updated_at timestamp
        updates.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())

        # Add WHERE clause params
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

    def delete_workflow(self, workflow_id: str, user_id: str) -> bool:
        """Delete a workflow.

        Args:
            workflow_id: Workflow identifier
            user_id: User ID to verify ownership

        Returns:
            True if deleted, False if not found/unauthorized
        """
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
        include_drafts: bool = True,
        drafts_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[WorkflowRecord], int]:
        """List workflows for a user.

        Args:
            user_id: User ID to filter by
            include_drafts: If True, include draft workflows (default True for LLM use)
            drafts_only: If True, only return drafts (overrides include_drafts)
            limit: Maximum number of workflows to return
            offset: Offset for pagination

        Returns:
            Tuple of (workflows list, total count)
        """
        # Build WHERE clause based on draft filtering
        where_clauses = ["user_id = ?"]
        params: List[Any] = [user_id]

        if drafts_only:
            where_clauses.append("is_draft = 1")
        elif not include_drafts:
            where_clauses.append("is_draft = 0")

        where_sql = " AND ".join(where_clauses)

        with self._conn() as conn:
            # Get total count
            count_row = conn.execute(
                f"SELECT COUNT(*) FROM workflows WHERE {where_sql}",
                params,
            ).fetchone()
            total_count = count_row[0] if count_row else 0

            # Get paginated results
            rows = conn.execute(
                f"""
                SELECT id, user_id, name, description, domain, tags,
                       nodes, edges, inputs, outputs, tree, doubts,
                       validation_score, validation_count, is_validated,
                       output_type, is_draft, created_at, updated_at
                FROM workflows
                WHERE {where_sql}
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
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
        include_drafts: bool = True,
        drafts_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[WorkflowRecord], int]:
        """Search workflows with filters.

        Args:
            user_id: User ID to filter by
            query: Text search in name/description
            domain: Filter by domain
            validated: Filter by validation status
            include_drafts: If True, include draft workflows (default True for LLM use)
            drafts_only: If True, only return drafts (overrides include_drafts)
            limit: Maximum results
            offset: Pagination offset

        Returns:
            Tuple of (workflows list, total count)
        """
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

        # Draft filtering
        if drafts_only:
            where_clauses.append("is_draft = 1")
        elif not include_drafts:
            where_clauses.append("is_draft = 0")

        where_sql = " AND ".join(where_clauses)

        with self._conn() as conn:
            # Get total count
            count_row = conn.execute(
                f"SELECT COUNT(*) FROM workflows WHERE {where_sql}",
                params,
            ).fetchone()
            total_count = count_row[0] if count_row else 0

            # Get paginated results
            rows = conn.execute(
                f"""
                SELECT id, user_id, name, description, domain, tags,
                       nodes, edges, inputs, outputs, tree, doubts,
                       validation_score, validation_count, is_validated,
                       output_type, is_draft, created_at, updated_at
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
        """Get list of unique domains for user's workflows.

        Args:
            user_id: User ID to filter by

        Returns:
            List of domain strings
        """
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
        """Convert database row to WorkflowRecord.

        Args:
            row: SQLite row object

        Returns:
            WorkflowRecord or None if row is invalid
        """
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
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logging.getLogger("backend.workflows").error(
                "Failed to deserialize workflow row id=%s: %s",
                row.get("id") if row else "unknown",
                e,
            )
            return None
