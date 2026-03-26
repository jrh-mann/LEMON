from __future__ import annotations

import sqlite3
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4

from .workflows import PUBLISH_VOTE_THRESHOLD


@dataclass(frozen=True)
class PackageMemberRecord:
    workflow_id: str
    role: str
    added_at: str


@dataclass(frozen=True)
class WorkflowPackageRecord:
    id: str
    user_id: str
    name: str
    description: str
    head_workflow_id: Optional[str]
    is_published: bool
    review_status: str
    net_votes: int
    published_at: Optional[str]
    created_at: str
    updated_at: str
    members: List[PackageMemberRecord] = field(default_factory=list)


@dataclass(frozen=True)
class PublicPackageSummary:
    id: str
    user_id: str
    name: str
    description: str
    domain: Optional[str]
    tags: List[str]
    is_validated: bool
    created_at: str
    updated_at: str
    is_published: bool
    review_status: str
    net_votes: int
    published_at: Optional[str]
    user_vote: Optional[int]
    workflow_count: int
    head_workflow_id: Optional[str]


class PackageStore:
    def __init__(self, db_path):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def create_package(
        self, user_id: str, name: str = "", description: str = ""
    ) -> WorkflowPackageRecord:
        now = datetime.now(timezone.utc).isoformat()
        package_id = f"pkg_{uuid4().hex}"
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO workflow_packages (
                    id, user_id, name, description, head_workflow_id,
                    is_published, review_status, net_votes, published_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, NULL, 0, 'unreviewed', 0, NULL, ?, ?)
                """,
                (package_id, user_id, name, description, now, now),
            )
            conn.commit()
        package = self.get_package(package_id, user_id)
        if package is None:
            raise RuntimeError("Failed to load newly created package")
        return package

    def get_package(
        self, package_id: str, user_id: str
    ) -> Optional[WorkflowPackageRecord]:
        with self._conn() as conn:
            pkg = conn.execute(
                "SELECT * FROM workflow_packages WHERE id = ? AND user_id = ?",
                (package_id, user_id),
            ).fetchone()
            if pkg is None:
                return None
            members = conn.execute(
                "SELECT workflow_id, role, created_at FROM workflow_package_members WHERE package_id = ? ORDER BY created_at ASC",
                (package_id,),
            ).fetchall()
        return WorkflowPackageRecord(
            id=pkg["id"],
            user_id=pkg["user_id"],
            name=pkg["name"],
            description=pkg["description"],
            head_workflow_id=pkg["head_workflow_id"],
            is_published=bool(pkg["is_published"]),
            review_status=pkg["review_status"],
            net_votes=pkg["net_votes"],
            published_at=pkg["published_at"],
            created_at=pkg["created_at"],
            updated_at=pkg["updated_at"],
            members=[
                PackageMemberRecord(
                    workflow_id=m["workflow_id"],
                    role=m["role"],
                    added_at=m["created_at"],
                )
                for m in members
            ],
        )

    def list_packages(self, user_id: str) -> List[WorkflowPackageRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id FROM workflow_packages WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
        return [
            pkg
            for row in rows
            if (pkg := self.get_package(row["id"], user_id)) is not None
        ]

    def update_package(
        self,
        package_id: str,
        user_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        head_workflow_id: Optional[str] = None,
        is_published: Optional[bool] = None,
        review_status: Optional[str] = None,
        net_votes: Optional[int] = None,
        published_at: Optional[str] = None,
    ) -> bool:
        updates = []
        params = []
        values: Dict[str, object] = {
            "name": name,
            "description": description,
            "head_workflow_id": head_workflow_id,
            "is_published": is_published,
            "review_status": review_status,
            "net_votes": net_votes,
            "published_at": published_at,
        }
        for key, value in values.items():
            if value is not None:
                updates.append(f"{key} = ?")
                params.append(value)
        if not updates:
            return True
        updates.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())
        params.extend([package_id, user_id])
        with self._conn() as conn:
            result = conn.execute(
                f"UPDATE workflow_packages SET {', '.join(updates)} WHERE id = ? AND user_id = ?",
                params,
            )
            conn.commit()
            return result.rowcount > 0

    def delete_package(self, package_id: str, user_id: str) -> bool:
        with self._conn() as conn:
            result = conn.execute(
                "DELETE FROM workflow_packages WHERE id = ? AND user_id = ?",
                (package_id, user_id),
            )
            conn.commit()
            return result.rowcount > 0

    def add_workflow_to_package(
        self, package_id: str, workflow_id: str, *, role: str = "dependency"
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO workflow_package_members (package_id, workflow_id, role, created_at) VALUES (?, ?, ?, ?)",
                (package_id, workflow_id, role, now),
            )
            conn.commit()

    def remove_workflow_from_package(self, package_id: str, workflow_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM workflow_package_members WHERE package_id = ? AND workflow_id = ?",
                (package_id, workflow_id),
            )
            conn.commit()

    def get_workflow_package_id(self, workflow_id: str) -> Optional[str]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT package_id FROM workflow_package_members WHERE workflow_id = ?",
                (workflow_id,),
            ).fetchone()
        return row["package_id"] if row else None

    def set_member_role(self, package_id: str, workflow_id: str, role: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE workflow_package_members SET role = ? WHERE package_id = ? AND workflow_id = ?",
                (role, package_id, workflow_id),
            )
            conn.commit()

    def list_published_packages(
        self,
        *,
        review_status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[List[WorkflowPackageRecord], int]:
        where = ["is_published = 1"]
        params: List[object] = []
        if review_status is not None:
            where.append("review_status = ?")
            params.append(review_status)
        where_sql = " AND ".join(where)
        with self._conn() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS count FROM workflow_packages WHERE {where_sql}",
                params,
            ).fetchone()["count"]
            rows = conn.execute(
                f"SELECT id, user_id FROM workflow_packages WHERE {where_sql} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        packages = [
            pkg
            for row in rows
            if (pkg := self.get_package(row["id"], row["user_id"])) is not None
        ]
        return packages, total

    def list_public_package_summaries(
        self,
        *,
        viewer_user_id: str,
        review_status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[List[PublicPackageSummary], int]:
        where = ["p.is_published = 1"]
        params: List[object] = []
        if review_status is not None:
            where.append("p.review_status = ?")
            params.append(review_status)
        where_sql = " AND ".join(where)
        with self._conn() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS count FROM workflow_packages p WHERE {where_sql}",
                params,
            ).fetchone()["count"]
            rows = conn.execute(
                f"""
                SELECT
                    p.id,
                    p.user_id,
                    p.name AS package_name,
                    p.description AS package_description,
                    p.head_workflow_id,
                    p.is_published,
                    p.review_status,
                    p.net_votes,
                    p.published_at,
                    p.created_at,
                    p.updated_at,
                    w.name AS head_name,
                    w.description AS head_description,
                    w.domain AS head_domain,
                    w.tags AS head_tags,
                    w.is_validated AS head_validated,
                    uv.vote AS user_vote,
                    COUNT(m.workflow_id) AS workflow_count
                FROM workflow_packages p
                LEFT JOIN workflows w ON w.id = p.head_workflow_id AND w.user_id = p.user_id
                LEFT JOIN workflow_package_members m ON m.package_id = p.id
                LEFT JOIN workflow_package_votes uv ON uv.package_id = p.id AND uv.user_id = ?
                WHERE {where_sql}
                GROUP BY p.id, p.user_id, p.name, p.description, p.head_workflow_id,
                         p.is_published, p.review_status, p.net_votes, p.published_at,
                         p.created_at, p.updated_at, w.name, w.description, w.domain,
                         w.tags, w.is_validated, uv.vote
                ORDER BY p.updated_at DESC
                LIMIT ? OFFSET ?
                """,
                [viewer_user_id, *params, limit, offset],
            ).fetchall()
        summaries = [
            PublicPackageSummary(
                id=row["id"],
                user_id=row["user_id"],
                name=row["head_name"] or row["package_name"] or "Empty package",
                description=row["head_description"] or row["package_description"] or "",
                domain=row["head_domain"],
                tags=json.loads(row["head_tags"]) if row["head_tags"] else [],
                is_validated=bool(row["head_validated"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                is_published=bool(row["is_published"]),
                review_status=row["review_status"],
                net_votes=row["net_votes"],
                published_at=row["published_at"],
                user_vote=row["user_vote"],
                workflow_count=row["workflow_count"],
                head_workflow_id=row["head_workflow_id"],
            )
            for row in rows
        ]
        return summaries, total

    def cast_vote(self, package_id: str, user_id: str, vote: int) -> Dict[str, object]:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO workflow_package_votes (package_id, user_id, vote, created_at) VALUES (?, ?, ?, ?) ON CONFLICT(package_id, user_id) DO UPDATE SET vote = excluded.vote, created_at = excluded.created_at",
                (package_id, user_id, vote, now),
            )
            net_votes = conn.execute(
                "SELECT COALESCE(SUM(vote), 0) AS total FROM workflow_package_votes WHERE package_id = ?",
                (package_id,),
            ).fetchone()["total"]
            review_status = (
                "reviewed" if net_votes >= PUBLISH_VOTE_THRESHOLD else "unreviewed"
            )
            conn.execute(
                "UPDATE workflow_packages SET net_votes = ?, review_status = ?, updated_at = ? WHERE id = ?",
                (net_votes, review_status, now, package_id),
            )
            conn.commit()
        return {
            "success": True,
            "net_votes": net_votes,
            "review_status": review_status,
            "user_vote": vote,
        }

    def remove_vote(self, package_id: str, user_id: str) -> Dict[str, object]:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM workflow_package_votes WHERE package_id = ? AND user_id = ?",
                (package_id, user_id),
            )
            net_votes = conn.execute(
                "SELECT COALESCE(SUM(vote), 0) AS total FROM workflow_package_votes WHERE package_id = ?",
                (package_id,),
            ).fetchone()["total"]
            review_status = (
                "reviewed" if net_votes >= PUBLISH_VOTE_THRESHOLD else "unreviewed"
            )
            conn.execute(
                "UPDATE workflow_packages SET net_votes = ?, review_status = ?, updated_at = ? WHERE id = ?",
                (net_votes, review_status, now, package_id),
            )
            conn.commit()
        return {
            "success": True,
            "net_votes": net_votes,
            "review_status": review_status,
            "user_vote": None,
        }

    def get_user_vote(self, package_id: str, user_id: str) -> Optional[int]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT vote FROM workflow_package_votes WHERE package_id = ? AND user_id = ?",
                (package_id, user_id),
            ).fetchone()
        return row["vote"] if row else None
