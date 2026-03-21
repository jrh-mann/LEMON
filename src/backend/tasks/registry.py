"""Unified task registry for in-progress chat tasks.

Indexes tasks by task_id (primary lookup) and (user_id, workflow_id)
(for resume after page refresh). Handles cancellation signaling and
stale entry purging.

Shared by ChatTask (chat turns) and BuilderTask (subworkflow builds).
Each task owns its own EventSink (SSE).
"""

from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Any, Dict, Optional, Protocol

logger = logging.getLogger(__name__)


class Registrable(Protocol):
    """Minimal interface a task must expose for registry indexing."""
    task_id: str
    user_id: str
    current_workflow_id: Optional[str]
    _cancelled: bool
    _notified: bool
    _created_at: float


class TaskRegistry:
    """Single source of truth for all in-progress chat tasks.

    Thread-safe — all mutations go through the internal lock.
    """

    # 10 min — 2x the task timeout for cleanup margin
    _TTL_SECONDS = 600.0

    def __init__(self) -> None:
        self._lock = Lock()
        self._by_task_id: Dict[str, Any] = {}
        self._by_workflow: Dict[tuple[str, str], Any] = {}

    def register(self, task: Any) -> None:
        """Register a task. Purges stale entries on each registration."""
        with self._lock:
            self._purge_stale()
            self._by_task_id[task.task_id] = task
            if task.current_workflow_id:
                self._by_workflow[(task.user_id, task.current_workflow_id)] = task

    def cancel(self, task_id: str) -> Optional[Any]:
        """Mark a task as cancelled. Returns the task if found."""
        with self._lock:
            task = self._by_task_id.get(task_id)
            if task:
                task._cancelled = True
            return task

    def mark_notified(self, task_id: str) -> bool:
        """Mark cancellation as notified. Returns True on first call only."""
        with self._lock:
            task = self._by_task_id.get(task_id)
            if not task or task._notified:
                return False
            task._notified = True
            return True

    def get(self, task_id: str) -> Optional[Any]:
        """Look up a task by task_id."""
        with self._lock:
            return self._by_task_id.get(task_id)

    def get_by_workflow(self, user_id: str, workflow_id: str) -> Optional[Any]:
        """Look up a task by (user_id, workflow_id) — used for resume."""
        with self._lock:
            return self._by_workflow.get((user_id, workflow_id))

    def unregister(self, task: Any) -> None:
        """Remove a task from the registry."""
        with self._lock:
            self._by_task_id.pop(task.task_id, None)
            if task.current_workflow_id:
                self._by_workflow.pop((task.user_id, task.current_workflow_id), None)

    def _purge_stale(self) -> None:
        """Remove tasks older than _TTL_SECONDS. Called under lock."""
        now = time.monotonic()
        stale = [
            tid for tid, t in self._by_task_id.items()
            if now - t._created_at > self._TTL_SECONDS
        ]
        for tid in stale:
            task = self._by_task_id.pop(tid, None)
            if task and task.current_workflow_id:
                self._by_workflow.pop((task.user_id, task.current_workflow_id), None)


# Module-level singleton — shared across chat routes and builder callbacks
task_registry = TaskRegistry()
