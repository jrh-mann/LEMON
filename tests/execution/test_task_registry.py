"""Tests for the TaskRegistry.

Verifies:
- Registration and lookup by task_id and (user_id, workflow_id)
- Cancel / mark_notified lifecycle
- Unregister cleanup
- Stale entry purging
"""

from __future__ import annotations

import time

import pytest

from src.backend.tasks.registry import TaskRegistry


class FakeTask:
    """Minimal task satisfying the Registrable protocol."""

    def __init__(self, task_id: str, user_id: str, workflow_id: str | None = None):
        self.task_id = task_id
        self.user_id = user_id
        self.current_workflow_id = workflow_id
        self._cancelled = False
        self._notified = False
        self._created_at = time.monotonic()


class TestRegistration:
    def test_register_and_get(self):
        reg = TaskRegistry()
        task = FakeTask("t1", "u1", "wf1")
        reg.register(task)
        assert reg.get("t1") is task

    def test_get_nonexistent(self):
        reg = TaskRegistry()
        assert reg.get("nope") is None

    def test_get_by_workflow(self):
        reg = TaskRegistry()
        task = FakeTask("t1", "u1", "wf1")
        reg.register(task)
        assert reg.get_by_workflow("u1", "wf1") is task

    def test_get_by_workflow_nonexistent(self):
        reg = TaskRegistry()
        assert reg.get_by_workflow("u1", "wf_missing") is None

    def test_register_without_workflow_id(self):
        """Tasks without a workflow_id should still be findable by task_id."""
        reg = TaskRegistry()
        task = FakeTask("t1", "u1", None)
        reg.register(task)
        assert reg.get("t1") is task
        assert reg.get_by_workflow("u1", "") is None


class TestCancelNotify:
    def test_cancel_sets_flag(self):
        reg = TaskRegistry()
        task = FakeTask("t1", "u1", "wf1")
        reg.register(task)
        result = reg.cancel("t1")
        assert result is task
        assert task._cancelled

    def test_cancel_nonexistent(self):
        reg = TaskRegistry()
        assert reg.cancel("nope") is None

    def test_mark_notified_first_call_true(self):
        reg = TaskRegistry()
        task = FakeTask("t1", "u1")
        reg.register(task)
        assert reg.mark_notified("t1") is True

    def test_mark_notified_second_call_false(self):
        """Only the first mark_notified call returns True."""
        reg = TaskRegistry()
        task = FakeTask("t1", "u1")
        reg.register(task)
        assert reg.mark_notified("t1") is True
        assert reg.mark_notified("t1") is False

    def test_mark_notified_nonexistent(self):
        reg = TaskRegistry()
        assert reg.mark_notified("nope") is False


class TestUnregister:
    def test_unregister_removes_both_indexes(self):
        reg = TaskRegistry()
        task = FakeTask("t1", "u1", "wf1")
        reg.register(task)
        reg.unregister(task)
        assert reg.get("t1") is None
        assert reg.get_by_workflow("u1", "wf1") is None

    def test_unregister_nonexistent_is_safe(self):
        """Unregistering a task that was never registered doesn't raise."""
        reg = TaskRegistry()
        task = FakeTask("t1", "u1", "wf1")
        reg.unregister(task)  # Should not raise


class TestStalePurge:
    def test_stale_entries_purged(self):
        """Tasks older than TTL are purged when a new task is registered."""
        reg = TaskRegistry()
        reg._TTL_SECONDS = 0.01  # Very short TTL for testing

        old_task = FakeTask("old", "u1", "wf_old")
        reg.register(old_task)

        time.sleep(0.02)  # Wait past TTL

        new_task = FakeTask("new", "u1", "wf_new")
        reg.register(new_task)  # Triggers purge

        assert reg.get("old") is None
        assert reg.get_by_workflow("u1", "wf_old") is None
        assert reg.get("new") is new_task
