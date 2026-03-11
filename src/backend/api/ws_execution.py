"""Socket.IO handlers for stepped workflow execution.

Provides visual workflow execution by emitting events for each node
visited so the frontend can highlight nodes in real-time. The conn_id
parameter throughout this module is the Socket.IO session ID (sid).

Events emitted to client:
- execution_step: {node_id, node_type, node_label, step_index, execution_id}
- execution_paused: {execution_id, current_node_id}
- execution_resumed: {execution_id}
- execution_complete: {success, output, path, error, execution_id}
- execution_error: {error, execution_id}
- execution_log: {execution_id, log_type, ...details}
"""

from __future__ import annotations

import logging
import time
import threading
from dataclasses import dataclass, field
from threading import Event, Lock
from typing import Any, Dict, Optional
from uuid import uuid4

from .ws_registry import ConnectionRegistry
from ..execution.interpreter import TreeInterpreter
from ..utils.flowchart import tree_from_flowchart
from ..storage.workflows import WorkflowStore
from ..execution.preparation import prepare_workflow_execution
from ..validation.workflow_validator import WorkflowValidator

logger = logging.getLogger("backend.api")

# Workflow validator instance for pre-execution validation
_workflow_validator = WorkflowValidator()

# ---------- Execution state (pause/resume support) ----------

_EXECUTION_STATE: Dict[str, Dict[str, Any]] = {}
_EXECUTION_LOCK = Lock()
_EXECUTION_TTL_SECONDS = 600.0


def _purge_stale_executions_locked(now: float) -> None:
    stale = [
        eid for eid, state in _EXECUTION_STATE.items()
        if now - state.get("created_at", now) > _EXECUTION_TTL_SECONDS
    ]
    for eid in stale:
        _EXECUTION_STATE.pop(eid, None)


def _register_execution(execution_id: str, conn_id: str) -> None:
    with _EXECUTION_LOCK:
        now = time.monotonic()
        _purge_stale_executions_locked(now)
        _EXECUTION_STATE[execution_id] = {
            "conn_id": conn_id,
            "paused": False,
            "stopped": False,
            "pause_event": Event(),
            "created_at": now,
        }
        _EXECUTION_STATE[execution_id]["pause_event"].set()


def _pause_execution(execution_id: str) -> bool:
    with _EXECUTION_LOCK:
        state = _EXECUTION_STATE.get(execution_id)
        if not state:
            return False
        state["paused"] = True
        state["pause_event"].clear()
        return True


def _resume_execution(execution_id: str) -> bool:
    with _EXECUTION_LOCK:
        state = _EXECUTION_STATE.get(execution_id)
        if not state:
            return False
        state["paused"] = False
        state["pause_event"].set()
        return True


def _stop_execution(execution_id: str) -> bool:
    with _EXECUTION_LOCK:
        state = _EXECUTION_STATE.get(execution_id)
        if not state:
            return False
        state["stopped"] = True
        state["pause_event"].set()
        return True


def _is_execution_stopped(execution_id: str) -> bool:
    with _EXECUTION_LOCK:
        state = _EXECUTION_STATE.get(execution_id)
        return bool(state and state.get("stopped"))


def _is_execution_paused(execution_id: str) -> bool:
    with _EXECUTION_LOCK:
        state = _EXECUTION_STATE.get(execution_id)
        return bool(state and state.get("paused"))


def _get_pause_event(execution_id: str) -> Optional[Event]:
    with _EXECUTION_LOCK:
        state = _EXECUTION_STATE.get(execution_id)
        return state.get("pause_event") if state else None


def _clear_execution(execution_id: str) -> None:
    with _EXECUTION_LOCK:
        _EXECUTION_STATE.pop(execution_id, None)


# -- Log-emission config for on_step -------------------------------------------
# Fields present on most step events that should be forwarded to execution_log.
_COMMON_LOG_FIELDS = [
    "node_id", "node_label", "parent_node_id",
    "subworkflow_id", "subworkflow_name", "subworkflow_stack",
]

# event_type -> (log_type, extra fields to copy, whether to also call emit_step)
_EVENT_LOG_MAP: Dict[str, tuple] = {
    "decision_evaluated": ("decision", [
        "condition_expression", "input_name", "input_value",
        "comparator", "compare_value", "compare_value2", "result", "branch_taken",
    ], True),
    "calculation_completed": ("calculation", [
        "output_name", "operator", "operands", "result", "formula",
    ], True),
    "start_executed": ("start", ["inputs"], True),
    "end_reached": ("end", ["output"], True),
}


# ---------- Execution task ----------

@dataclass
class SteppedExecutionTask:
    """Manages stepped workflow execution with pause/resume support.

    Wraps TreeInterpreter to emit events for each step, allowing
    the frontend to highlight nodes in real-time.
    """

    registry: ConnectionRegistry
    workflow_store: WorkflowStore
    user_id: str
    conn_id: str
    execution_id: str
    workflow: Dict[str, Any]
    inputs: Dict[str, Any]
    speed_ms: int = 500
    done: Event = field(default_factory=Event)
    current_node_id: Optional[str] = None

    def _emit(self, event: str, payload: dict) -> None:
        """Emit a JSON message via the registry (sync, from background thread)."""
        self.registry.send_to_sync(self.conn_id, event, payload)

    def is_stopped(self) -> bool:
        return _is_execution_stopped(self.execution_id)

    def emit_step(self, step_info: Dict[str, Any]) -> None:
        self.current_node_id = step_info.get("node_id")
        if step_info.get("subworkflow_id"):
            self._emit("subflow_step", {
                "execution_id": self.execution_id,
                "parent_node_id": step_info.get("parent_node_id"),
                "subworkflow_id": step_info.get("subworkflow_id"),
                "node_id": step_info.get("node_id"),
                "node_type": step_info.get("node_type"),
                "node_label": step_info.get("node_label"),
                "step_index": step_info.get("step_index"),
            })
        else:
            self._emit("execution_step", {
                **step_info,
                "execution_id": self.execution_id,
            })

    def emit_paused(self) -> None:
        self._emit("execution_paused", {
            "execution_id": self.execution_id,
            "current_node_id": self.current_node_id,
        })

    def emit_resumed(self) -> None:
        self._emit("execution_resumed", {"execution_id": self.execution_id})

    def emit_complete(
        self,
        success: bool,
        output: Optional[Any] = None,
        path: Optional[list] = None,
        error: Optional[str] = None,
    ) -> None:
        self._emit("execution_complete", {
            "execution_id": self.execution_id,
            "success": success,
            "output": output,
            "path": path or [],
            "error": error,
        })

    def emit_error(self, error: str) -> None:
        self._emit("execution_error", {
            "execution_id": self.execution_id,
            "error": error,
        })

    def _emit_log(self, log_type: str, step_info: Dict[str, Any],
                  extra_fields: list) -> None:
        """Emit an execution_log event with common + extra fields from step_info.

        Builds a payload containing execution_id, log_type, and any common /
        extra fields that are present (non-None) in step_info.
        """
        payload: Dict[str, Any] = {
            "execution_id": self.execution_id,
            "log_type": log_type,
        }
        for key in _COMMON_LOG_FIELDS + extra_fields:
            val = step_info.get(key)
            if val is not None:
                payload[key] = val
        self._emit("execution_log", payload)

    def on_step(self, step_info: Dict[str, Any]) -> None:
        """Callback for TreeInterpreter -- called before each node.

        Handles emitting step events, checking stop, waiting on pause,
        and applying speed delay.
        """
        if self.is_stopped():
            raise StoppedExecutionError("Execution stopped by user")

        event_type = step_info.get("event_type")

        # -- Subworkflow events: emit a direct event AND an execution_log -----
        if event_type == "subflow_start":
            self._emit("subflow_start", {
                "execution_id": self.execution_id,
                "parent_node_id": step_info.get("parent_node_id"),
                "subworkflow_id": step_info.get("subworkflow_id"),
                "subworkflow_name": step_info.get("subworkflow_name"),
                "nodes": step_info.get("nodes", []),
                "edges": step_info.get("edges", []),
            })
            # Log uses parent_node_id as node_id, subworkflow_name as node_label
            self._emit_log("subflow_start",
                           {**step_info,
                            "node_id": step_info.get("parent_node_id"),
                            "node_label": step_info.get("subworkflow_name")},
                           [])
            return

        elif event_type == "subflow_step":
            self._emit("subflow_step", {
                "execution_id": self.execution_id,
                "parent_node_id": step_info.get("parent_node_id"),
                "subworkflow_id": step_info.get("subworkflow_id"),
                "node_id": step_info.get("node_id"),
                "node_type": step_info.get("node_type"),
                "node_label": step_info.get("node_label"),
                "step_index": step_info.get("step_index"),
            })
            # Only log if node_type isn't handled by _EVENT_LOG_MAP (those emit
            # their own log via a subsequent on_step call from the interpreter).
            node_type = step_info.get("node_type")
            if node_type not in ("decision", "calculation", "start", "end"):
                self._emit_log("subflow_step", step_info, ["node_type"])

        elif event_type == "subflow_complete":
            self._emit("subflow_complete", {
                "execution_id": self.execution_id,
                "parent_node_id": step_info.get("parent_node_id"),
                "subworkflow_id": step_info.get("subworkflow_id"),
                "subworkflow_name": step_info.get("subworkflow_name"),
                "success": step_info.get("success"),
                "output": step_info.get("output"),
                "error": step_info.get("error"),
            })
            # Log uses parent_node_id as node_id, subworkflow_name as node_label
            self._emit_log("subflow_complete",
                           {**step_info,
                            "node_id": step_info.get("parent_node_id"),
                            "node_label": step_info.get("subworkflow_name")},
                           ["success", "output", "error"])
            return

        # -- Standard node events: use the mapping table ----------------------
        elif event_type in _EVENT_LOG_MAP:
            log_type, extra_fields, do_emit_step = _EVENT_LOG_MAP[event_type]
            self._emit_log(log_type, step_info, extra_fields)
            if do_emit_step:
                self.emit_step(step_info)

        # -- Fallback: unknown event_type, just emit the step -----------------
        else:
            self.emit_step(step_info)

        # -- Pause / resume gate (unchanged) ----------------------------------
        pause_event = _get_pause_event(self.execution_id)
        if pause_event:
            was_paused = _is_execution_paused(self.execution_id)
            if was_paused:
                self.emit_paused()
            while not pause_event.wait(timeout=0.1):
                if self.is_stopped():
                    raise StoppedExecutionError("Execution stopped by user")
            if was_paused:
                self.emit_resumed()

        # -- Step delay for visualization (skip in instant mode) --------------
        if self.speed_ms > 0:
            delay_seconds = self.speed_ms / 1000.0
            elapsed = 0.0
            while elapsed < delay_seconds:
                if self.is_stopped():
                    raise StoppedExecutionError("Execution stopped by user")
                sleep_time = min(0.1, delay_seconds - elapsed)
                self.registry.sleep_sync(sleep_time)
                elapsed += sleep_time

    def run(self) -> None:
        """Execute the workflow step-by-step."""
        try:
            nodes = self.workflow.get("nodes", [])
            edges = self.workflow.get("edges", [])

            if not nodes:
                self.emit_error("Workflow has no nodes")
                return

            tree, preparation_error, _ = prepare_workflow_execution(
                nodes=nodes,
                edges=edges,
                variables=self.workflow.get("variables", []),
            )
            if preparation_error or tree is None:
                self.emit_error(preparation_error or "Workflow has no start node")
                return

            workflow_variables = self.workflow.get("variables", [])
            workflow_outputs = self.workflow.get("outputs", [])

            interpreter = TreeInterpreter(
                tree=tree,
                variables=workflow_variables,
                outputs=workflow_outputs,
                workflow_store=self.workflow_store,
                user_id=self.user_id,
                output_type=self.workflow.get("output_type", "string"),
            )

            result = interpreter.execute(self.inputs, on_step=self.on_step)

            self.emit_complete(
                success=result.success,
                output=result.output,
                path=result.path,
                error=result.error,
            )

        except StoppedExecutionError:
            self.emit_complete(success=False, error="Execution stopped by user", path=[])
        except Exception as exc:
            logger.exception("Stepped execution failed")
            self.emit_error(str(exc))
        finally:
            self.done.set()
            _clear_execution(self.execution_id)


class StoppedExecutionError(Exception):
    """Raised when execution is stopped by user."""
    pass


# ---------- Handler functions ----------

def handle_execute_workflow(
    registry: ConnectionRegistry,
    *,
    conn_id: str,
    workflow_store: WorkflowStore,
    user_id: str,
    payload: Dict[str, Any],
) -> None:
    """Handle execute_workflow message — starts stepped execution."""
    workflow = payload.get("workflow")
    inputs = payload.get("inputs", {})
    speed_ms = payload.get("speed_ms", 500)
    execution_id = payload.get("execution_id")

    if not isinstance(workflow, dict):
        registry.send_to_sync(conn_id, "execution_error", {
            "error": "Invalid workflow format",
            "execution_id": execution_id,
        })
        return

    tree, preparation_error, validation_errors = prepare_workflow_execution(
        nodes=workflow.get("nodes", []),
        edges=workflow.get("edges", []),
        variables=workflow.get("variables", []),
    )
    if preparation_error:
        registry.send_to_sync(conn_id, "execution_error", {
            "execution_id": execution_id,
            "error": (
                f"Workflow validation failed:\n{preparation_error}"
                if validation_errors else preparation_error
            ),
            "validation_errors": [
                {"code": e.code, "message": e.message, "node_id": e.node_id}
                for e in validation_errors or []
            ],
        })
        return

    if not isinstance(speed_ms, int) or speed_ms < 0:
        speed_ms = 0
    elif speed_ms > 2000:
        speed_ms = 2000

    if not isinstance(execution_id, str) or not execution_id.strip():
        execution_id = uuid4().hex

    _register_execution(execution_id, conn_id)

    task = SteppedExecutionTask(
        registry=registry,
        workflow_store=workflow_store,
        user_id=user_id,
        conn_id=conn_id,
        execution_id=execution_id,
        workflow=workflow,
        inputs=inputs,
        speed_ms=speed_ms,
    )

    registry.send_to_sync(conn_id, "execution_started", {"execution_id": execution_id})

    threading.Thread(target=task.run, daemon=True, name=f"ws-exec-{execution_id}").start()


def handle_pause_execution(*, payload: Dict[str, Any]) -> None:
    """Handle pause_execution message."""
    execution_id = payload.get("execution_id")
    if not isinstance(execution_id, str) or not execution_id.strip():
        return
    if _pause_execution(execution_id):
        logger.info("Paused execution %s", execution_id)
    else:
        logger.warning("Failed to pause execution %s - not found", execution_id)


def handle_resume_execution(*, payload: Dict[str, Any]) -> None:
    """Handle resume_execution message."""
    execution_id = payload.get("execution_id")
    if not isinstance(execution_id, str) or not execution_id.strip():
        return
    if _resume_execution(execution_id):
        logger.info("Resumed execution %s", execution_id)
    else:
        logger.warning("Failed to resume execution %s - not found", execution_id)


def handle_stop_execution(*, payload: Dict[str, Any]) -> None:
    """Handle stop_execution message."""
    execution_id = payload.get("execution_id")
    if not isinstance(execution_id, str) or not execution_id.strip():
        return
    if _stop_execution(execution_id):
        logger.info("Stopped execution %s", execution_id)
    else:
        logger.warning("Failed to stop execution %s - not found", execution_id)
