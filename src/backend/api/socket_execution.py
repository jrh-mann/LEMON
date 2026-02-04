"""Socket handlers for stepped workflow execution.

Provides visual workflow execution by running workflows step-by-step,
emitting events for each node visited so the frontend can highlight nodes in real-time.

Events emitted to client:
- execution_step: {node_id, node_type, node_label, step_index, execution_id}
- execution_paused: {execution_id, current_node_id}
- execution_resumed: {execution_id}
- execution_complete: {success, output, path, error, execution_id}
- execution_error: {error, execution_id}
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from threading import Event, Lock
from typing import Any, Dict, Optional
from uuid import uuid4

from flask import request
from flask_socketio import SocketIO

from ..execution.interpreter import TreeInterpreter
from ..utils.flowchart import tree_from_flowchart
from ..storage.workflows import WorkflowStore
from ..validation.workflow_validator import WorkflowValidator

logger = logging.getLogger("backend.api")

# Workflow validator instance for pre-execution validation
_workflow_validator = WorkflowValidator()

# Global state for execution tasks (pause/resume support)
_EXECUTION_STATE: Dict[str, Dict[str, Any]] = {}
_EXECUTION_LOCK = Lock()
_EXECUTION_TTL_SECONDS = 600.0  # 10 minutes


def _purge_stale_executions_locked(now: float) -> None:
    """Remove stale execution records that have exceeded TTL."""
    stale = [
        eid for eid, state in _EXECUTION_STATE.items()
        if now - state.get("created_at", now) > _EXECUTION_TTL_SECONDS
    ]
    for eid in stale:
        _EXECUTION_STATE.pop(eid, None)


def _register_execution(execution_id: str, sid: str) -> None:
    """Register a new execution task."""
    with _EXECUTION_LOCK:
        now = time.monotonic()
        _purge_stale_executions_locked(now)
        _EXECUTION_STATE[execution_id] = {
            "sid": sid,
            "paused": False,
            "stopped": False,
            "pause_event": Event(),
            "created_at": now,
        }
        # Set event by default (not paused)
        _EXECUTION_STATE[execution_id]["pause_event"].set()


def _pause_execution(execution_id: str) -> bool:
    """Pause an execution. Returns True if execution was found and paused."""
    with _EXECUTION_LOCK:
        state = _EXECUTION_STATE.get(execution_id)
        if not state:
            return False
        state["paused"] = True
        state["pause_event"].clear()  # Block on wait()
        return True


def _resume_execution(execution_id: str) -> bool:
    """Resume a paused execution. Returns True if execution was found and resumed."""
    with _EXECUTION_LOCK:
        state = _EXECUTION_STATE.get(execution_id)
        if not state:
            return False
        state["paused"] = False
        state["pause_event"].set()  # Unblock wait()
        return True


def _stop_execution(execution_id: str) -> bool:
    """Stop an execution. Returns True if execution was found."""
    with _EXECUTION_LOCK:
        state = _EXECUTION_STATE.get(execution_id)
        if not state:
            return False
        state["stopped"] = True
        state["pause_event"].set()  # Unblock if paused so it can exit
        return True


def _is_execution_stopped(execution_id: str) -> bool:
    """Check if execution has been stopped."""
    with _EXECUTION_LOCK:
        state = _EXECUTION_STATE.get(execution_id)
        return bool(state and state.get("stopped"))


def _is_execution_paused(execution_id: str) -> bool:
    """Check if execution is paused."""
    with _EXECUTION_LOCK:
        state = _EXECUTION_STATE.get(execution_id)
        return bool(state and state.get("paused"))


def _get_pause_event(execution_id: str) -> Optional[Event]:
    """Get the pause event for blocking."""
    with _EXECUTION_LOCK:
        state = _EXECUTION_STATE.get(execution_id)
        return state.get("pause_event") if state else None


def _clear_execution(execution_id: str) -> None:
    """Clean up execution state."""
    with _EXECUTION_LOCK:
        _EXECUTION_STATE.pop(execution_id, None)


@dataclass
class SteppedExecutionTask:
    """Manages stepped workflow execution with pause/resume support.
    
    Wraps TreeInterpreter to emit socket events for each step,
    allowing the frontend to highlight nodes in real-time.
    """
    socketio: SocketIO
    workflow_store: WorkflowStore
    user_id: str
    sid: str
    execution_id: str
    workflow: Dict[str, Any]  # Full workflow state {nodes, edges, ...}
    inputs: Dict[str, Any]    # Input values {input_id: value}
    speed_ms: int = 500       # Delay between steps in milliseconds
    done: Event = field(default_factory=Event)
    current_node_id: Optional[str] = None

    def is_stopped(self) -> bool:
        """Check if execution has been stopped by user."""
        return _is_execution_stopped(self.execution_id)

    def emit_step(self, step_info: Dict[str, Any]) -> None:
        """Emit execution_step event to client for node highlighting."""
        self.current_node_id = step_info.get("node_id")
        self.socketio.emit(
            "execution_step",
            {
                **step_info,
                "execution_id": self.execution_id,
            },
            to=self.sid,
        )

    def emit_paused(self) -> None:
        """Emit execution_paused event when user pauses."""
        self.socketio.emit(
            "execution_paused",
            {
                "execution_id": self.execution_id,
                "current_node_id": self.current_node_id,
            },
            to=self.sid,
        )

    def emit_resumed(self) -> None:
        """Emit execution_resumed event when user resumes."""
        self.socketio.emit(
            "execution_resumed",
            {"execution_id": self.execution_id},
            to=self.sid,
        )

    def emit_complete(
        self,
        success: bool,
        output: Optional[Any] = None,
        path: Optional[list] = None,
        error: Optional[str] = None,
    ) -> None:
        """Emit execution_complete event when workflow finishes."""
        self.socketio.emit(
            "execution_complete",
            {
                "execution_id": self.execution_id,
                "success": success,
                "output": output,
                "path": path or [],
                "error": error,
            },
            to=self.sid,
        )

    def emit_error(self, error: str) -> None:
        """Emit execution_error event on failure."""
        self.socketio.emit(
            "execution_error",
            {
                "execution_id": self.execution_id,
                "error": error,
            },
            to=self.sid,
        )

    def on_step(self, step_info: Dict[str, Any]) -> None:
        """Callback for TreeInterpreter - called before each node.
        
        Handles:
        1. Emitting step event to frontend
        2. Checking for stop signal
        3. Waiting if paused
        4. Applying speed delay
        """
        # Check if stopped before processing
        if self.is_stopped():
            raise StoppedExecutionError("Execution stopped by user")

        # Emit step event for UI highlighting
        self.emit_step(step_info)

        # Check for pause and wait if needed
        pause_event = _get_pause_event(self.execution_id)
        if pause_event:
            was_paused = _is_execution_paused(self.execution_id)
            if was_paused:
                self.emit_paused()

            # Wait for resume (or timeout to check stop)
            while not pause_event.wait(timeout=0.1):
                if self.is_stopped():
                    raise StoppedExecutionError("Execution stopped by user")

            if was_paused:
                self.emit_resumed()

        # Apply step delay for visualization
        delay_seconds = self.speed_ms / 1000.0
        # Use small intervals to check for stop during delay
        elapsed = 0.0
        while elapsed < delay_seconds:
            if self.is_stopped():
                raise StoppedExecutionError("Execution stopped by user")
            sleep_time = min(0.1, delay_seconds - elapsed)
            self.socketio.sleep(sleep_time)
            elapsed += sleep_time

    def run(self) -> None:
        """Execute the workflow step-by-step."""
        try:
            # Build tree from workflow
            nodes = self.workflow.get("nodes", [])
            edges = self.workflow.get("edges", [])

            if not nodes:
                self.emit_error("Workflow has no nodes")
                return

            tree = tree_from_flowchart(nodes, edges)
            if not tree or "start" not in tree:
                self.emit_error("Workflow has no start node")
                return

            # Get variables/outputs from workflow metadata
            workflow_variables = self.workflow.get("variables", [])
            workflow_outputs = self.workflow.get("outputs", [])

            # Create interpreter with on_step callback
            interpreter = TreeInterpreter(
                tree=tree,
                inputs=workflow_variables,
                outputs=workflow_outputs,
                workflow_store=self.workflow_store,
                user_id=self.user_id,
                output_type=self.workflow.get("output_type", "string"),
            )

            # Execute with step callback
            result = interpreter.execute(self.inputs, on_step=self.on_step)

            # Emit completion
            self.emit_complete(
                success=result.success,
                output=result.output,
                path=result.path,
                error=result.error,
            )

        except StoppedExecutionError:
            # User stopped execution - this is expected
            self.emit_complete(
                success=False,
                error="Execution stopped by user",
                path=[],
            )
        except Exception as exc:
            logger.exception("Stepped execution failed")
            self.emit_error(str(exc))
        finally:
            self.done.set()
            _clear_execution(self.execution_id)


class StoppedExecutionError(Exception):
    """Raised when execution is stopped by user."""
    pass


def handle_execute_workflow(
    socketio: SocketIO,
    *,
    workflow_store: WorkflowStore,
    user_id: str,
    payload: Dict[str, Any],
) -> None:
    """Handle execute_workflow socket event.
    
    Starts stepped execution of a workflow with visual feedback.
    
    Payload:
        workflow: Full workflow state {nodes, edges, inputs, outputs, ...}
        inputs: Input values {input_id: value}
        speed_ms: Optional delay between steps (100-2000ms, default 500)
        execution_id: Optional ID for this execution
    """
    sid = request.sid
    workflow = payload.get("workflow")
    inputs = payload.get("inputs", {})
    speed_ms = payload.get("speed_ms", 500)
    execution_id = payload.get("execution_id")

    # Validate workflow format
    if not isinstance(workflow, dict):
        socketio.emit(
            "execution_error",
            {"error": "Invalid workflow format", "execution_id": execution_id},
            to=sid,
        )
        return

    # Run comprehensive workflow validation before execution
    is_valid, validation_errors = _workflow_validator.validate(workflow, strict=True)
    if not is_valid:
        error_message = _workflow_validator.format_errors(validation_errors)
        socketio.emit(
            "execution_error",
            {
                "execution_id": execution_id,
                "error": f"Workflow validation failed:\n{error_message}",
                "validation_errors": [
                    {"code": e.code, "message": e.message, "node_id": e.node_id}
                    for e in validation_errors
                ],
            },
            to=sid,
        )
        return

    # Validate speed_ms range
    if not isinstance(speed_ms, int) or speed_ms < 100:
        speed_ms = 100
    elif speed_ms > 2000:
        speed_ms = 2000

    # Generate execution ID if not provided
    if not isinstance(execution_id, str) or not execution_id.strip():
        execution_id = uuid4().hex

    # Register execution for pause/resume tracking
    _register_execution(execution_id, sid)

    # Create and start execution task
    task = SteppedExecutionTask(
        socketio=socketio,
        workflow_store=workflow_store,
        user_id=user_id,
        sid=sid,
        execution_id=execution_id,
        workflow=workflow,
        inputs=inputs,
        speed_ms=speed_ms,
    )

    # Emit initial event with execution_id
    socketio.emit(
        "execution_started",
        {"execution_id": execution_id},
        to=sid,
    )

    # Run in background
    socketio.start_background_task(task.run)


def handle_pause_execution(
    socketio: SocketIO,
    *,
    payload: Dict[str, Any],
) -> None:
    """Handle pause_execution socket event."""
    execution_id = payload.get("execution_id")
    if not isinstance(execution_id, str) or not execution_id.strip():
        return

    if _pause_execution(execution_id):
        logger.info("Paused execution %s", execution_id)
    else:
        logger.warning("Failed to pause execution %s - not found", execution_id)


def handle_resume_execution(
    socketio: SocketIO,
    *,
    payload: Dict[str, Any],
) -> None:
    """Handle resume_execution socket event."""
    execution_id = payload.get("execution_id")
    if not isinstance(execution_id, str) or not execution_id.strip():
        return

    if _resume_execution(execution_id):
        logger.info("Resumed execution %s", execution_id)
    else:
        logger.warning("Failed to resume execution %s - not found", execution_id)


def handle_stop_execution(
    socketio: SocketIO,
    *,
    payload: Dict[str, Any],
) -> None:
    """Handle stop_execution socket event."""
    execution_id = payload.get("execution_id")
    if not isinstance(execution_id, str) or not execution_id.strip():
        return

    if _stop_execution(execution_id):
        logger.info("Stopped execution %s", execution_id)
    else:
        logger.warning("Failed to stop execution %s - not found", execution_id)
