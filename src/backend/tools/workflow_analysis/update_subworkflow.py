"""Tool for updating an existing subworkflow by resuming its background builder.

The main orchestrator calls this when it needs to modify a previously-built
subworkflow. The tool:
1. Loads the workflow and its build_history from the DB
2. Rejects if the workflow is still being built (building=True)
3. Spawns a background thread with an orchestrator pre-loaded with the
   previous conversation history so the builder has full context
4. Returns immediately so the main orchestrator can continue
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict
from uuid import uuid4

from ..core import Tool, ToolParameter, extract_session_deps
from ..constants import builder_semaphore, MAX_BUILD_HISTORY_MESSAGES

logger = logging.getLogger(__name__)


def _run_subworkflow_updater(
    workflow_id: str,
    instructions: str,
    repo_root: Any,
    workflow_store: Any,
    user_id: str,
    build_history: list,
    ws_registry: Any,
    conn_id: str,
) -> None:
    """Background thread: update a subworkflow using a fresh orchestrator
    pre-loaded with the previous build conversation.

    Args:
        workflow_id: ID of the workflow to update
        instructions: What changes to make
        repo_root: Path to repo root for tool construction
        workflow_store: WorkflowStore instance for DB access
        user_id: Owner user ID
        build_history: Previous builder conversation to pre-load
        ws_registry: ConnectionRegistry for emitting events (can be None)
        conn_id: Connection ID for emitting events (can be None)
    """
    # Import here to avoid circular imports (builder_callbacks → tools.constants → tools → this file)
    from ...api.builder_callbacks import BackgroundBuilderCallbacks
    from ...api.ws_chat import _task_registry

    # Set up unified callbacks — emits same chat_* events as main orchestrator,
    # tagged with workflow_id so frontend routes them to chatStore.conversations[workflow_id]
    bg_task_id = f"bg_{uuid4().hex[:8]}"
    cb = BackgroundBuilderCallbacks(
        ws_registry, conn_id, workflow_id,
        user_id=user_id, task_id=bg_task_id,
    )
    response_text = ""

    # Register as active task so handle_resume_task can reconnect after refresh.
    _task_registry.register(cb)

    # Acquire semaphore to limit concurrent builder threads
    with builder_semaphore:
        try:
            from ...agents.orchestrator_factory import build_orchestrator

            orchestrator = build_orchestrator(repo_root)
            orchestrator.workflow_store = workflow_store
            orchestrator.user_id = user_id
            orchestrator.current_workflow_id = workflow_id
            orchestrator.repo_root = repo_root
            orchestrator.ws_registry = ws_registry
            orchestrator.conn_id = conn_id
            cb.orchestrator = orchestrator

            # Pre-load the previous builder's conversation so the LLM has
            # full context of how the workflow was originally built
            orchestrator.conversation.history = list(build_history)

            logger.info(
                "Background updater started for subworkflow %s (history=%d messages): %s",
                workflow_id, len(build_history), instructions[:100],
            )

            # Emit the instructions as a user message so the frontend shows it during streaming
            cb.emit_user_message(instructions)
            cb.emit_progress("Updating workflow...", event="start")

            # Run the orchestrator with the update instructions
            # Uses the same callback pattern as SocketChatTask.run()
            # Turn wraps the update turn — no audit logger for background builds
            from ...agents.turn import Turn
            update_turn = Turn(instructions, f"bg_{workflow_id}")
            update_turn.start()
            try:
                response_text = orchestrator.respond(
                    instructions, turn=update_turn, allow_tools=True,
                    stream=cb.stream_chunk,
                    on_tool_event=cb.on_tool_event,
                    should_cancel=cb.is_cancelled,
                    thinking=True,
                    on_thinking=cb.stream_thinking,
                )
                update_turn.complete(response_text)
            except Exception as update_exc:
                update_turn.fail(str(update_exc))
                raise
            finally:
                update_turn.commit(orchestrator.conversation)

            # Persist the updated conversation history and clear building flag.
            # Cap history to prevent unbounded DB blob growth.
            build_hist = orchestrator.conversation.history
            if len(build_hist) > MAX_BUILD_HISTORY_MESSAGES:
                build_hist = build_hist[-MAX_BUILD_HISTORY_MESSAGES:]
            workflow_store.update_workflow(
                workflow_id, user_id,
                building=False,
                build_history=build_hist,
            )

            logger.info("Background updater finished for subworkflow %s", workflow_id)

        except Exception as exc:
            logger.error(
                "Background updater FAILED for subworkflow %s: %s",
                workflow_id, exc, exc_info=True,
            )
            # Clear building flag even on failure so the workflow isn't stuck
            try:
                workflow_store.update_workflow(
                    workflow_id, user_id, building=False,
                )
            except Exception as inner_exc:
                logger.error(
                    "Failed to clear building flag for %s: %s",
                    workflow_id, inner_exc,
                )
            # Notify frontend so it can clear the "Building..." state
            if ws_registry and conn_id:
                ws_registry.send_to_sync(conn_id, "build_error", {
                    "workflow_id": workflow_id,
                    "error": str(exc),
                })
        finally:
            # Always emit chat_response to signal build completion to frontend
            cb.emit_response(response_text)
            # Mark done and unregister so handle_resume_task knows the build finished
            cb.done.set()
            _task_registry.unregister(cb)
            # Notify frontend for library badge refresh
            if ws_registry and conn_id:
                ws_registry.send_to_sync(
                    conn_id, "subworkflow_ready",
                    {"workflow_id": workflow_id},
                )


class UpdateSubworkflowTool(Tool):
    """Update an existing subworkflow by resuming its background builder.

    Loads the subworkflow's previous build conversation from the DB,
    spawns a background orchestrator with that context, and applies
    the requested changes. Returns immediately.
    """

    name = "update_subworkflow"
    description = (
        "Update an existing subworkflow by resuming its builder with new instructions. "
        "The builder retains full context of how the workflow was originally built. "
        "Returns immediately while the update happens in the background."
    )
    parameters = [
        ToolParameter(
            "workflow_id", "string",
            "ID of the subworkflow to update",
            required=True,
        ),
        ToolParameter(
            "instructions", "string",
            (
                "Detailed instructions for what to change. Be specific about "
                "which nodes to add/modify/remove and what logic to change."
            ),
            required=True,
        ),
    ]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        # --- Validate parameters ---
        workflow_id = args.get("workflow_id")
        if not workflow_id or not isinstance(workflow_id, str):
            return {
                "success": False,
                "error": "'workflow_id' is required",
                "error_code": "MISSING_WORKFLOW_ID",
            }

        instructions = args.get("instructions")
        if not instructions or not isinstance(instructions, str) or not instructions.strip():
            return {
                "success": False,
                "error": "'instructions' is required and must be a non-empty string",
                "error_code": "MISSING_INSTRUCTIONS",
            }

        # --- Extract session dependencies ---
        session_state, workflow_store, user_id, err = extract_session_deps(
            kwargs, action="update subworkflow",
        )
        if err:
            return err

        repo_root = session_state.get("repo_root")
        if not repo_root:
            return {
                "success": False,
                "error": "No repo_root in session state",
                "error_code": "NO_REPO_ROOT",
            }

        # --- Load the workflow from DB ---
        workflow = workflow_store.get_workflow(workflow_id, user_id)
        if not workflow:
            return {
                "success": False,
                "error": f"Subworkflow '{workflow_id}' not found in your library",
                "error_code": "NOT_FOUND",
            }

        # --- Atomically set building flag (prevents concurrent updates) ---
        if not workflow_store.try_set_building(workflow_id, user_id):
            return {
                "success": False,
                "error": (
                    f"Subworkflow '{workflow_id}' is still being built. "
                    f"Wait for it to finish before updating."
                ),
                "error_code": "STILL_BUILDING",
            }

        # --- Build the update prompt with context ---
        updater_prompt = (
            f"You are updating the subworkflow '{workflow.name}' (ID: {workflow_id}).\n"
            f"Output type: {workflow.output_type or 'string'}\n\n"
            f"Update instructions:\n{instructions.strip()}\n\n"
            f"Use workflow_id={workflow_id} in all tool calls.\n"
            f"Review the existing nodes and make the requested changes."
        )

        # --- Spawn background updater thread ---
        ws_registry = session_state.get("ws_registry")
        conn_id = session_state.get("conn_id")

        # Notify frontend that this subworkflow is being rebuilt so the
        # library page can show the "Building..." badge
        if ws_registry and conn_id:
            ws_registry.send_to_sync(conn_id, "subworkflow_building", {
                "workflow_id": workflow_id,
                "name": workflow.name,
                "building": True,
            })

        thread = threading.Thread(
            target=_run_subworkflow_updater,
            args=(
                workflow_id, updater_prompt, repo_root, workflow_store,
                user_id, workflow.build_history, ws_registry, conn_id,
            ),
            daemon=True,
            name=f"subworkflow-updater-{workflow_id}",
        )
        thread.start()

        logger.info(
            "Spawned background updater for subworkflow %s ('%s')",
            workflow_id, workflow.name,
        )

        return {
            "success": True,
            "workflow_id": workflow_id,
            "name": workflow.name,
            "status": "updating",
            "message": (
                f"Subworkflow '{workflow.name}' is being updated in the background. "
                f"The builder has context from the original build and will apply your changes."
            ),
        }
