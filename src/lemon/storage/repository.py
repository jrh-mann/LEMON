"""Workflow repository implementations.

This module provides storage backends for workflows:
- SQLiteWorkflowRepository: Persistent SQLite storage
- InMemoryWorkflowRepository: In-memory storage for testing
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Union

from lemon.core.blocks import (
    Block,
    InputBlock,
    DecisionBlock,
    OutputBlock,
    WorkflowRefBlock,
    Workflow,
    WorkflowMetadata,
    WorkflowSummary,
    Connection,
    BlockType,
)
from lemon.core.interfaces import WorkflowFilters
from lemon.core.exceptions import WorkflowNotFoundError


# -----------------------------------------------------------------------------
# Schema
# -----------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS workflows (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    domain TEXT,
    tags TEXT DEFAULT '[]',
    creator_id TEXT,
    validation_score REAL DEFAULT 0.0,
    validation_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    definition TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_workflows_domain ON workflows(domain);
CREATE INDEX IF NOT EXISTS idx_workflows_validation_score ON workflows(validation_score);
CREATE INDEX IF NOT EXISTS idx_workflows_creator ON workflows(creator_id);
CREATE INDEX IF NOT EXISTS idx_workflows_name ON workflows(name);

CREATE TABLE IF NOT EXISTS workflow_inputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL,
    input_name TEXT NOT NULL,
    input_type TEXT NOT NULL,
    FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_workflow_inputs_workflow ON workflow_inputs(workflow_id);
CREATE INDEX IF NOT EXISTS idx_workflow_inputs_name ON workflow_inputs(input_name);
CREATE INDEX IF NOT EXISTS idx_workflow_inputs_type ON workflow_inputs(input_type);

CREATE TABLE IF NOT EXISTS workflow_outputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL,
    output_value TEXT NOT NULL,
    FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_workflow_outputs_workflow ON workflow_outputs(workflow_id);
CREATE INDEX IF NOT EXISTS idx_workflow_outputs_value ON workflow_outputs(output_value);

CREATE TABLE IF NOT EXISTS workflow_refs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_workflow_refs_workflow ON workflow_refs(workflow_id);
CREATE INDEX IF NOT EXISTS idx_workflow_refs_ref ON workflow_refs(ref_id);

CREATE TABLE IF NOT EXISTS workflow_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_workflow_tags_workflow ON workflow_tags(workflow_id);
CREATE INDEX IF NOT EXISTS idx_workflow_tags_tag ON workflow_tags(tag);
"""


# -----------------------------------------------------------------------------
# SQLite Repository
# -----------------------------------------------------------------------------


class SQLiteWorkflowRepository:
    """SQLite-backed workflow repository.

    This implementation stores workflows in a SQLite database with:
    - Main workflows table with metadata and JSON definition
    - Denormalized tables for searchable fields (inputs, outputs, tags, refs)

    Usage:
        repo = SQLiteWorkflowRepository("workflows.db")
        repo.save(workflow)
        workflow = repo.get("workflow-id")
    """

    def __init__(self, db_path: Union[str, Path] = ":memory:"):
        """Initialize repository.

        Args:
            db_path: Path to SQLite database file, or ":memory:" for in-memory.
        """
        self.db_path = str(db_path)
        self._is_memory = self.db_path == ":memory:"
        self._persistent_conn: Optional[sqlite3.Connection] = None

        # For in-memory databases, keep a persistent connection
        if self._is_memory:
            self._persistent_conn = self._create_connection()

        self._init_schema()

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new database connection with proper settings."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Get a database connection with proper settings."""
        if self._is_memory and self._persistent_conn:
            # For in-memory, use the persistent connection
            try:
                yield self._persistent_conn
                self._persistent_conn.commit()
            except Exception:
                self._persistent_conn.rollback()
                raise
        else:
            # For file-based, create new connection each time
            conn = self._create_connection()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _init_schema(self) -> None:
        """Initialize database schema."""
        with self._connection() as conn:
            conn.executescript(SCHEMA)

    # -------------------------------------------------------------------------
    # CRUD Operations
    # -------------------------------------------------------------------------

    def save(self, workflow: Workflow) -> str:
        """Save a workflow. Updates if exists, creates if not."""
        with self._connection() as conn:
            # Serialize the workflow definition
            definition = self._serialize_workflow(workflow)

            # Check if exists
            existing = conn.execute(
                "SELECT id FROM workflows WHERE id = ?", (workflow.id,)
            ).fetchone()

            now = datetime.now(timezone.utc).isoformat()

            if existing:
                # Update existing
                conn.execute(
                    """
                    UPDATE workflows SET
                        name = ?,
                        description = ?,
                        domain = ?,
                        tags = ?,
                        creator_id = ?,
                        validation_score = ?,
                        validation_count = ?,
                        updated_at = ?,
                        definition = ?
                    WHERE id = ?
                    """,
                    (
                        workflow.metadata.name,
                        workflow.metadata.description,
                        workflow.metadata.domain,
                        json.dumps(workflow.metadata.tags),
                        workflow.metadata.creator_id,
                        workflow.metadata.validation_score,
                        workflow.metadata.validation_count,
                        now,
                        definition,
                        workflow.id,
                    ),
                )
                # Clear and re-insert denormalized data
                self._clear_denormalized(conn, workflow.id)
            else:
                # Insert new
                conn.execute(
                    """
                    INSERT INTO workflows (
                        id, name, description, domain, tags, creator_id,
                        validation_score, validation_count, created_at, updated_at, definition
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        workflow.id,
                        workflow.metadata.name,
                        workflow.metadata.description,
                        workflow.metadata.domain,
                        json.dumps(workflow.metadata.tags),
                        workflow.metadata.creator_id,
                        workflow.metadata.validation_score,
                        workflow.metadata.validation_count,
                        workflow.metadata.created_at.isoformat(),
                        now,
                        definition,
                    ),
                )

            # Insert denormalized data for search
            self._insert_denormalized(conn, workflow)

        return workflow.id

    def get(self, workflow_id: str) -> Optional[Workflow]:
        """Get a workflow by ID."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM workflows WHERE id = ?", (workflow_id,)
            ).fetchone()

            if not row:
                return None

            return self._deserialize_workflow(dict(row))

    def delete(self, workflow_id: str) -> bool:
        """Delete a workflow. Returns True if deleted."""
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM workflows WHERE id = ?", (workflow_id,)
            )
            return cursor.rowcount > 0

    def exists(self, workflow_id: str) -> bool:
        """Check if a workflow exists."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM workflows WHERE id = ?", (workflow_id,)
            ).fetchone()
            return row is not None

    def list(self, filters: Optional[WorkflowFilters] = None) -> List[WorkflowSummary]:
        """List workflows matching filters."""
        filters = filters or WorkflowFilters()

        query = """
            SELECT DISTINCT w.*
            FROM workflows w
        """
        joins = []
        conditions = []
        params: List[Any] = []

        # Build joins and conditions based on filters
        if filters.has_input or filters.has_input_type:
            joins.append("LEFT JOIN workflow_inputs wi ON w.id = wi.workflow_id")
            if filters.has_input:
                conditions.append("wi.input_name = ?")
                params.append(filters.has_input)
            if filters.has_input_type:
                conditions.append("wi.input_type = ?")
                params.append(filters.has_input_type)

        if filters.has_output:
            joins.append("LEFT JOIN workflow_outputs wo ON w.id = wo.workflow_id")
            conditions.append("wo.output_value = ?")
            params.append(filters.has_output)

        if filters.tags:
            joins.append("LEFT JOIN workflow_tags wt ON w.id = wt.workflow_id")
            placeholders = ",".join("?" * len(filters.tags))
            conditions.append(f"wt.tag IN ({placeholders})")
            params.extend(filters.tags)

        if filters.domain:
            conditions.append("w.domain = ?")
            params.append(filters.domain)

        if filters.min_validation is not None:
            conditions.append("w.validation_score >= ?")
            params.append(filters.min_validation)

        if filters.max_validation is not None:
            conditions.append("w.validation_score <= ?")
            params.append(filters.max_validation)

        if filters.creator_id:
            conditions.append("w.creator_id = ?")
            params.append(filters.creator_id)

        if filters.name_contains:
            conditions.append("w.name LIKE ?")
            params.append(f"%{filters.name_contains}%")

        if filters.is_validated is not None:
            if filters.is_validated:
                conditions.append("w.validation_score >= 80 AND w.validation_count >= 10")
            else:
                conditions.append("(w.validation_score < 80 OR w.validation_count < 10)")

        # Build final query
        if joins:
            query += " " + " ".join(joins)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY w.updated_at DESC"

        if filters.limit:
            query += " LIMIT ?"
            params.append(filters.limit)
        if filters.offset:
            query += " OFFSET ?"
            params.append(filters.offset)

        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()

            summaries = []
            for row in rows:
                row_dict = dict(row)
                summaries.append(self._row_to_summary(conn, row_dict))

            return summaries

    def update_validation(
        self, workflow_id: str, score: float, count: int
    ) -> bool:
        """Update validation score and count."""
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE workflows
                SET validation_score = ?, validation_count = ?, updated_at = ?
                WHERE id = ?
                """,
                (score, count, datetime.now(timezone.utc).isoformat(), workflow_id),
            )
            return cursor.rowcount > 0

    # -------------------------------------------------------------------------
    # Search helpers
    # -------------------------------------------------------------------------

    def list_domains(self) -> List[str]:
        """Get all unique domains."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT domain FROM workflows WHERE domain IS NOT NULL ORDER BY domain"
            ).fetchall()
            return [row["domain"] for row in rows]

    def list_tags(self) -> List[str]:
        """Get all unique tags."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT tag FROM workflow_tags ORDER BY tag"
            ).fetchall()
            return [row["tag"] for row in rows]

    def count(self, filters: Optional[WorkflowFilters] = None) -> int:
        """Count workflows matching filters."""
        # Reuse list() but only need count
        return len(self.list(filters))

    # -------------------------------------------------------------------------
    # Serialization helpers
    # -------------------------------------------------------------------------

    def _serialize_workflow(self, workflow: Workflow) -> str:
        """Serialize workflow blocks and connections to JSON."""
        data = {
            "blocks": [b.model_dump() for b in workflow.blocks],
            "connections": [c.model_dump() for c in workflow.connections],
        }
        return json.dumps(data)

    def _deserialize_workflow(self, row: Dict[str, Any]) -> Workflow:
        """Deserialize a database row to a Workflow."""
        definition = json.loads(row["definition"])

        # Reconstruct blocks with proper types
        blocks: List[Block] = []
        for block_data in definition.get("blocks", []):
            block_type = block_data.get("type")
            if block_type == BlockType.INPUT or block_type == "input":
                blocks.append(InputBlock(**block_data))
            elif block_type == BlockType.DECISION or block_type == "decision":
                blocks.append(DecisionBlock(**block_data))
            elif block_type == BlockType.OUTPUT or block_type == "output":
                blocks.append(OutputBlock(**block_data))
            elif block_type == BlockType.WORKFLOW_REF or block_type == "workflow_ref":
                blocks.append(WorkflowRefBlock(**block_data))

        # Reconstruct connections
        connections = [
            Connection(**c) for c in definition.get("connections", [])
        ]

        # Parse timestamps
        created_at = datetime.fromisoformat(row["created_at"])
        updated_at = datetime.fromisoformat(row["updated_at"])

        # Parse tags
        tags = json.loads(row["tags"]) if row["tags"] else []

        metadata = WorkflowMetadata(
            name=row["name"],
            description=row["description"] or "",
            domain=row["domain"],
            tags=tags,
            creator_id=row["creator_id"],
            validation_score=row["validation_score"],
            validation_count=row["validation_count"],
            created_at=created_at,
            updated_at=updated_at,
        )

        return Workflow(
            id=row["id"],
            metadata=metadata,
            blocks=blocks,
            connections=connections,
        )

    def _row_to_summary(
        self, conn: sqlite3.Connection, row: Dict[str, Any]
    ) -> WorkflowSummary:
        """Convert a database row to WorkflowSummary."""
        # Get inputs
        input_rows = conn.execute(
            "SELECT input_name FROM workflow_inputs WHERE workflow_id = ?",
            (row["id"],),
        ).fetchall()
        input_names = [r["input_name"] for r in input_rows]

        # Get outputs
        output_rows = conn.execute(
            "SELECT output_value FROM workflow_outputs WHERE workflow_id = ?",
            (row["id"],),
        ).fetchall()
        output_values = [r["output_value"] for r in output_rows]

        # Parse tags
        tags = json.loads(row["tags"]) if row["tags"] else []

        # Determine confidence
        validation_count = row["validation_count"]
        if validation_count == 0:
            confidence = "none"
        elif validation_count < 10:
            confidence = "low"
        elif validation_count < 50:
            confidence = "medium"
        else:
            confidence = "high"

        # Determine is_validated
        is_validated = (
            row["validation_score"] >= 80 and validation_count >= 10
        )

        return WorkflowSummary(
            id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            domain=row["domain"],
            tags=tags,
            validation_score=row["validation_score"],
            validation_count=validation_count,
            confidence=confidence,
            is_validated=is_validated,
            input_names=input_names,
            output_values=output_values,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _clear_denormalized(self, conn: sqlite3.Connection, workflow_id: str) -> None:
        """Clear denormalized data for a workflow."""
        conn.execute("DELETE FROM workflow_inputs WHERE workflow_id = ?", (workflow_id,))
        conn.execute("DELETE FROM workflow_outputs WHERE workflow_id = ?", (workflow_id,))
        conn.execute("DELETE FROM workflow_refs WHERE workflow_id = ?", (workflow_id,))
        conn.execute("DELETE FROM workflow_tags WHERE workflow_id = ?", (workflow_id,))

    def _insert_denormalized(self, conn: sqlite3.Connection, workflow: Workflow) -> None:
        """Insert denormalized data for search."""
        # Inputs
        for block in workflow.input_blocks:
            conn.execute(
                "INSERT INTO workflow_inputs (workflow_id, input_name, input_type) VALUES (?, ?, ?)",
                (workflow.id, block.name, block.input_type.value),
            )

        # Outputs
        for block in workflow.output_blocks:
            conn.execute(
                "INSERT INTO workflow_outputs (workflow_id, output_value) VALUES (?, ?)",
                (workflow.id, block.value),
            )

        # Workflow refs
        for block in workflow.workflow_ref_blocks:
            conn.execute(
                "INSERT INTO workflow_refs (workflow_id, ref_id) VALUES (?, ?)",
                (workflow.id, block.ref_id),
            )

        # Tags
        for tag in workflow.metadata.tags:
            conn.execute(
                "INSERT INTO workflow_tags (workflow_id, tag) VALUES (?, ?)",
                (workflow.id, tag),
            )


# -----------------------------------------------------------------------------
# In-Memory Repository (for testing)
# -----------------------------------------------------------------------------


class InMemoryWorkflowRepository:
    """In-memory workflow repository for testing.

    This provides the same interface as SQLiteWorkflowRepository
    but stores everything in memory. Useful for unit tests.
    """

    def __init__(self):
        self._workflows: Dict[str, Workflow] = {}

    def save(self, workflow: Workflow) -> str:
        """Save a workflow."""
        # Update the updated_at timestamp
        workflow.metadata.updated_at = datetime.now(timezone.utc)
        self._workflows[workflow.id] = workflow
        return workflow.id

    def get(self, workflow_id: str) -> Optional[Workflow]:
        """Get a workflow by ID."""
        return self._workflows.get(workflow_id)

    def delete(self, workflow_id: str) -> bool:
        """Delete a workflow."""
        if workflow_id in self._workflows:
            del self._workflows[workflow_id]
            return True
        return False

    def exists(self, workflow_id: str) -> bool:
        """Check if workflow exists."""
        return workflow_id in self._workflows

    def list(self, filters: Optional[WorkflowFilters] = None) -> List[WorkflowSummary]:
        """List workflows matching filters."""
        filters = filters or WorkflowFilters()
        results = []

        for workflow in self._workflows.values():
            if not self._matches_filters(workflow, filters):
                continue
            results.append(WorkflowSummary.from_workflow(workflow))

        # Sort by updated_at descending
        results.sort(key=lambda w: w.updated_at, reverse=True)

        # Apply pagination
        if filters.offset:
            results = results[filters.offset:]
        if filters.limit:
            results = results[: filters.limit]

        return results

    def update_validation(
        self, workflow_id: str, score: float, count: int
    ) -> bool:
        """Update validation score and count."""
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return False

        workflow.metadata.validation_score = score
        workflow.metadata.validation_count = count
        workflow.metadata.updated_at = datetime.now(timezone.utc)
        return True

    def list_domains(self) -> List[str]:
        """Get all unique domains."""
        domains = set()
        for workflow in self._workflows.values():
            if workflow.metadata.domain:
                domains.add(workflow.metadata.domain)
        return sorted(domains)

    def list_tags(self) -> List[str]:
        """Get all unique tags."""
        tags = set()
        for workflow in self._workflows.values():
            tags.update(workflow.metadata.tags)
        return sorted(tags)

    def _matches_filters(self, workflow: Workflow, filters: WorkflowFilters) -> bool:
        """Check if workflow matches filters."""
        if filters.domain and workflow.metadata.domain != filters.domain:
            return False

        if filters.tags:
            if not any(tag in workflow.metadata.tags for tag in filters.tags):
                return False

        if filters.has_input:
            if filters.has_input not in workflow.input_names:
                return False

        if filters.has_input_type:
            types = [b.input_type.value for b in workflow.input_blocks]
            if filters.has_input_type not in types:
                return False

        if filters.has_output:
            if filters.has_output not in workflow.output_values:
                return False

        if filters.min_validation is not None:
            if workflow.metadata.validation_score < filters.min_validation:
                return False

        if filters.max_validation is not None:
            if workflow.metadata.validation_score > filters.max_validation:
                return False

        if filters.creator_id:
            if workflow.metadata.creator_id != filters.creator_id:
                return False

        if filters.name_contains:
            if filters.name_contains.lower() not in workflow.metadata.name.lower():
                return False

        if filters.is_validated is not None:
            is_val = workflow.metadata.is_validated
            if filters.is_validated != is_val:
                return False

        return True
