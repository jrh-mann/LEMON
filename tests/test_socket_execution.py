"""Tests for stepped workflow execution."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from threading import Event
import time

from src.backend.api.socket_execution import (
    SteppedExecutionTask,
    StoppedExecutionError,
    _register_execution,
    _pause_execution,
    _resume_execution,
    _stop_execution,
    _is_execution_stopped,
    _is_execution_paused,
    _clear_execution,
)


class TestExecutionStateManagement:
    """Test execution state tracking for pause/resume/stop."""

    def test_register_execution(self):
        """Test registering a new execution."""
        execution_id = "test-exec-1"
        sid = "socket-123"
        
        _register_execution(execution_id, sid)
        
        assert not _is_execution_stopped(execution_id)
        assert not _is_execution_paused(execution_id)
        
        # Cleanup
        _clear_execution(execution_id)

    def test_pause_and_resume_execution(self):
        """Test pausing and resuming an execution."""
        execution_id = "test-exec-2"
        sid = "socket-456"
        
        _register_execution(execution_id, sid)
        
        # Pause
        result = _pause_execution(execution_id)
        assert result is True
        assert _is_execution_paused(execution_id)
        
        # Resume
        result = _resume_execution(execution_id)
        assert result is True
        assert not _is_execution_paused(execution_id)
        
        # Cleanup
        _clear_execution(execution_id)

    def test_stop_execution(self):
        """Test stopping an execution."""
        execution_id = "test-exec-3"
        sid = "socket-789"
        
        _register_execution(execution_id, sid)
        
        result = _stop_execution(execution_id)
        assert result is True
        assert _is_execution_stopped(execution_id)
        
        # Cleanup
        _clear_execution(execution_id)

    def test_pause_nonexistent_execution(self):
        """Test pausing a non-existent execution returns False."""
        result = _pause_execution("nonexistent-id")
        assert result is False

    def test_stop_nonexistent_execution(self):
        """Test stopping a non-existent execution returns False."""
        result = _stop_execution("nonexistent-id")
        assert result is False


class TestSteppedExecutionTask:
    """Test SteppedExecutionTask behavior."""

    @pytest.fixture
    def mock_socketio(self):
        """Create a mock SocketIO instance."""
        mock = Mock()
        mock.emit = Mock()
        mock.sleep = Mock(side_effect=lambda x: time.sleep(min(x, 0.01)))
        mock.start_background_task = Mock(side_effect=lambda fn: fn())
        return mock

    @pytest.fixture
    def mock_workflow_store(self):
        """Create a mock WorkflowStore."""
        return Mock()

    @pytest.fixture
    def simple_workflow(self):
        """Create a simple test workflow."""
        return {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start"},
                {"id": "decision1", "type": "decision", "label": "Age >= 18"},
                {"id": "out_adult", "type": "output", "label": "Adult"},
                {"id": "out_minor", "type": "output", "label": "Minor"},
            ],
            "edges": [
                {"from": "start", "to": "decision1"},
                {"from": "decision1", "to": "out_adult", "label": "Yes"},
                {"from": "decision1", "to": "out_minor", "label": "No"},
            ],
            "inputs": [
                {"id": "input_age_int", "name": "Age", "type": "int", "range": {"min": 0, "max": 120}},
            ],
            "outputs": [
                {"name": "Adult"},
                {"name": "Minor"},
            ],
        }

    def test_task_emits_step_events(self, mock_socketio, mock_workflow_store, simple_workflow):
        """Test that task emits execution_step events for each node."""
        execution_id = "test-step-events"
        _register_execution(execution_id, "sid-1")
        
        task = SteppedExecutionTask(
            socketio=mock_socketio,
            workflow_store=mock_workflow_store,
            user_id="user-1",
            sid="sid-1",
            execution_id=execution_id,
            workflow=simple_workflow,
            inputs={"input_age_int": 25},
            speed_ms=100,  # Fast for testing
        )
        
        task.run()
        
        # Should have emitted execution_step events
        step_calls = [
            call for call in mock_socketio.emit.call_args_list
            if call[0][0] == "execution_step"
        ]
        assert len(step_calls) >= 2  # At least start and one other node
        
        # Should have emitted execution_complete
        complete_calls = [
            call for call in mock_socketio.emit.call_args_list
            if call[0][0] == "execution_complete"
        ]
        assert len(complete_calls) == 1
        assert complete_calls[0][0][1]["success"] is True

    def test_task_detects_stop_signal(self, mock_socketio, mock_workflow_store, simple_workflow):
        """Test that task detects stop signal via is_stopped()."""
        execution_id = "test-stop-signal"
        _register_execution(execution_id, "sid-2")
        
        task = SteppedExecutionTask(
            socketio=mock_socketio,
            workflow_store=mock_workflow_store,
            user_id="user-1",
            sid="sid-2",
            execution_id=execution_id,
            workflow=simple_workflow,
            inputs={"input_age_int": 25},
            speed_ms=100,
        )
        
        # Verify task can detect stop
        assert not task.is_stopped()
        _stop_execution(execution_id)
        assert task.is_stopped()
        
        # Cleanup
        _clear_execution(execution_id)

    def test_emit_step_updates_current_node(self, mock_socketio, mock_workflow_store):
        """Test that emit_step updates current_node_id."""
        task = SteppedExecutionTask(
            socketio=mock_socketio,
            workflow_store=mock_workflow_store,
            user_id="user-1",
            sid="sid-3",
            execution_id="test-current-node",
            workflow={},
            inputs={},
            speed_ms=100,
        )
        
        assert task.current_node_id is None
        
        task.emit_step({"node_id": "node-1", "node_type": "start"})
        
        assert task.current_node_id == "node-1"

    def test_emit_complete_sends_correct_payload(self, mock_socketio, mock_workflow_store):
        """Test execution_complete event payload."""
        task = SteppedExecutionTask(
            socketio=mock_socketio,
            workflow_store=mock_workflow_store,
            user_id="user-1",
            sid="sid-4",
            execution_id="test-complete-payload",
            workflow={},
            inputs={},
            speed_ms=100,
        )
        
        task.emit_complete(
            success=True,
            output="Test Output",
            path=["start", "decision", "output"],
            error=None,
        )
        
        mock_socketio.emit.assert_called_with(
            "execution_complete",
            {
                "execution_id": "test-complete-payload",
                "success": True,
                "output": "Test Output",
                "path": ["start", "decision", "output"],
                "error": None,
            },
            to="sid-4",
        )

    def test_task_handles_empty_workflow(self, mock_socketio, mock_workflow_store):
        """Test that task handles empty workflow gracefully."""
        execution_id = "test-empty"
        _register_execution(execution_id, "sid-5")
        
        task = SteppedExecutionTask(
            socketio=mock_socketio,
            workflow_store=mock_workflow_store,
            user_id="user-1",
            sid="sid-5",
            execution_id=execution_id,
            workflow={"nodes": [], "edges": []},
            inputs={},
            speed_ms=100,
        )
        
        task.run()
        
        # Should emit error
        error_calls = [
            call for call in mock_socketio.emit.call_args_list
            if call[0][0] == "execution_error"
        ]
        assert len(error_calls) == 1
        assert "no nodes" in error_calls[0][0][1]["error"].lower()

    def test_task_handles_missing_start_node(self, mock_socketio, mock_workflow_store):
        """Test that task handles workflow without start node."""
        execution_id = "test-no-start"
        _register_execution(execution_id, "sid-6")
        
        task = SteppedExecutionTask(
            socketio=mock_socketio,
            workflow_store=mock_workflow_store,
            user_id="user-1",
            sid="sid-6",
            execution_id=execution_id,
            workflow={
                "nodes": [{"id": "output1", "type": "output", "label": "Done"}],
                "edges": [],
            },
            inputs={},
            speed_ms=100,
        )
        
        task.run()
        
        # Should complete (with the output node since it has no incoming edges)
        # or emit error - either is acceptable behavior
        complete_calls = [
            call for call in mock_socketio.emit.call_args_list
            if call[0][0] in ("execution_complete", "execution_error")
        ]
        assert len(complete_calls) >= 1


class TestStoppedExecutionError:
    """Test the StoppedExecutionError exception."""

    def test_exception_message(self):
        """Test that exception carries the message."""
        error = StoppedExecutionError("Test stop message")
        assert str(error) == "Test stop message"

    def test_exception_is_exception_subclass(self):
        """Test that StoppedExecutionError is an Exception."""
        assert issubclass(StoppedExecutionError, Exception)
