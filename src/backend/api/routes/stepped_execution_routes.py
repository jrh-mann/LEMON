"""Stepped execution routes: visual step-through with SSE streaming.

POST /api/workflows/{workflow_id}/execute  — SSE stream of execution events
POST /api/executions/{execution_id}/pause  — pause a running execution
POST /api/executions/{execution_id}/resume — resume a paused execution
POST /api/executions/{execution_id}/stop   — stop a running execution

These routes replace the Socket.IO execute_workflow / pause_execution /
resume_execution / stop_execution events.
"""

from __future__ import annotations

import logging
import threading
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Request
from starlette.responses import JSONResponse, StreamingResponse

from ..deps import require_auth
from ..sse import EventSink
from ..execution_task import (
    SteppedExecutionTask,
    register_execution,
    pause_execution,
    resume_execution,
    stop_execution,
)
from ...execution.preparation import prepare_workflow_execution
from ...storage.auth import AuthUser
from ...storage.workflows import WorkflowStore

logger = logging.getLogger("backend.api")


def register_stepped_execution_routes(
    app: FastAPI,
    *,
    workflow_store: WorkflowStore,
) -> None:
    """Register stepped execution endpoints on the FastAPI app."""
    router = APIRouter()

    @router.post("/api/workflows/{workflow_id}/execute")
    async def execute_workflow_sse(
        workflow_id: str,
        request: Request,
        user: AuthUser = Depends(require_auth),
    ) -> StreamingResponse:
        """Start a visual step-through execution, returning an SSE stream.

        Body: {workflow, inputs, speed_ms, execution_id}
        """
        payload = await request.json()
        workflow = payload.get("workflow")
        inputs = payload.get("inputs", {})
        speed_ms = payload.get("speed_ms", 500)
        execution_id = payload.get("execution_id")

        # Validate workflow format
        if not isinstance(workflow, dict):
            sink = EventSink()
            sink.push("execution_error", {
                "error": "Invalid workflow format",
                "execution_id": execution_id,
            })
            sink.close()
            return StreamingResponse(
                sink, media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        # Pre-validate workflow structure
        _, preparation_error, validation_errors = prepare_workflow_execution(
            nodes=workflow.get("nodes", []),
            edges=workflow.get("edges", []),
            variables=workflow.get("variables", []),
        )
        if preparation_error:
            sink = EventSink()
            sink.push("execution_error", {
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
            sink.close()
            return StreamingResponse(
                sink, media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        # Clamp speed_ms to valid range
        if not isinstance(speed_ms, int) or speed_ms < 0:
            speed_ms = 0
        elif speed_ms > 2000:
            speed_ms = 2000

        # Generate execution_id if not provided
        if not isinstance(execution_id, str) or not execution_id.strip():
            execution_id = uuid4().hex

        # Register for pause/resume/stop tracking
        register_execution(execution_id)

        # Create the SSE sink and execution task
        sink = EventSink()
        task = SteppedExecutionTask(
            sink=sink,
            workflow_store=workflow_store,
            user_id=user.id,
            execution_id=execution_id,
            workflow=workflow,
            inputs=inputs,
            speed_ms=speed_ms,
        )

        # Emit execution_started before spawning the thread so
        # it's the first event the client receives
        sink.push("execution_started", {"execution_id": execution_id})

        # Run the execution in a background thread
        threading.Thread(
            target=task.run, daemon=True, name=f"exec-{execution_id}",
        ).start()

        return StreamingResponse(
            sink, media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/api/executions/{execution_id}/pause")
    async def pause_execution_endpoint(
        execution_id: str,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        """Pause a running execution."""
        if pause_execution(execution_id):
            logger.info("Paused execution %s", execution_id)
            return JSONResponse({"ok": True})
        logger.warning("Failed to pause execution %s — not found", execution_id)
        return JSONResponse({"ok": False, "error": "Execution not found"}, status_code=404)

    @router.post("/api/executions/{execution_id}/resume")
    async def resume_execution_endpoint(
        execution_id: str,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        """Resume a paused execution."""
        if resume_execution(execution_id):
            logger.info("Resumed execution %s", execution_id)
            return JSONResponse({"ok": True})
        logger.warning("Failed to resume execution %s — not found", execution_id)
        return JSONResponse({"ok": False, "error": "Execution not found"}, status_code=404)

    @router.post("/api/executions/{execution_id}/stop")
    async def stop_execution_endpoint(
        execution_id: str,
        user: AuthUser = Depends(require_auth),
    ) -> JSONResponse:
        """Stop a running execution."""
        if stop_execution(execution_id):
            logger.info("Stopped execution %s", execution_id)
            return JSONResponse({"ok": True})
        logger.warning("Failed to stop execution %s — not found", execution_id)
        return JSONResponse({"ok": False, "error": "Execution not found"}, status_code=404)

    app.include_router(router)
