"""Tool for updating an existing subworkflow by resuming its background builder.

The main orchestrator calls this when it needs to modify a previously-built
subworkflow. The tool:
1. Loads the workflow and its build_history from the DB
2. Rejects if the workflow is still being built (building=True)
3. Spawns a background thread with an orchestrator pre-loaded with the
   previous conversation history so the builder has full context
4. Returns immediately so the main orchestrator can continue

The builder runs as an independent task with its own EventSink — it does not
share the parent ChatTask's SSE stream. The frontend connects via
POST /api/chat/resume when the user navigates to the subworkflow page.
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
    task: Any,
    build_depth: int = 1,
) -> None:
    """Background thread: update a subworkflow using a fresh orchestrator
    pre-loaded with the previous build conversation.

    Fully independent — no reference to the parent's EventSink. The builder
    owns its own sink via `task.sink`. The DB (building flag) is the only
    coordination channel with the parent.

    Args:
        workflow_id: ID of the workflow to update
        instructions: What changes to make
        repo_root: Path to repo root for tool construction
        workflow_store: WorkflowStore instance for DB access
        user_id: Owner user ID
        build_history: Previous builder conversation to pre-load
        task: BuilderTask — owns its own EventSink, provides callbacks
        build_depth: Nesting depth — child builders inherit parent's depth + 1.
    """
    from ...api.task_registry import task_registry as _task_registry

    response_text = ""

    # Acquire semaphore to limit concurrent builder threads
    with builder_semaphore:
        try:
            from ...agents.orchestrator_factory import build_orchestrator

            orchestrator = build_orchestrator(repo_root)
            orchestrator.workflow_store = workflow_store
            orchestrator.user_id = user_id
            orchestrator.current_workflow_id = workflow_id
            orchestrator.repo_root = repo_root
            # Builder's own sink — nested subworkflows will use this
            orchestrator.event_sink = task.sink
            # Propagate build depth so nested create_subworkflow is rejected
            # if we're already at MAX_BUILD_DEPTH
            orchestrator._build_depth = build_depth
            task.orchestrator = orchestrator

            # Pre-load the previous builder's conversation so the LLM has
            # full context of how the workflow was originally built
            orchestrator.conversation.history = list(build_history)

            logger.info(
                "Background updater started for subworkflow %s (history=%d messages): %s",
                workflow_id, len(build_history), instructions[:100],
            )

            # Emit the instructions as a user message so the frontend shows it
            task.emit_user_message(instructions)
            task.emit_progress("Updating workflow...", event="start")

            # Run the orchestrator with the update instructions
            from ...agents.turn import Turn
            update_turn = Turn(instructions, f"bg_{workflow_id}")
            update_turn.start()
            try:
                response_text = orchestrator.respond(
                    instructions, turn=update_turn, allow_tools=True,
                    stream=task.stream_chunk,
                    on_tool_event=task.on_tool_event,
                    should_cancel=task.is_cancelled,
                    thinking=True,
                    on_thinking=task.stream_thinking,
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
            # build_error is emitted on the builder's own sink (via
            # task.emit_response below) so the frontend sees it when
            # connected to the builder's stream.
        finally:
            # Emit chat_response on builder's own sink to signal completion
            task.emit_response(response_text)
            task.done.set()
            _task_registry.unregister(task)
            # Close the builder's own sink
            task.sink.close()


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

        # --- Create independent builder task with its own EventSink ---
        from ...api.builder_task import BuilderTask
        from ...api.sse import EventSink
        from ...api.task_registry import task_registry as _task_registry

        builder_sink = EventSink()
        bg_task_id = f"bg_{uuid4().hex[:8]}"
        builder = BuilderTask(
            sink=builder_sink,
            workflow_id=workflow_id,
            user_id=user_id,
            task_id=bg_task_id,
        )

        # Register before thread spawn so resume can find it immediately
        _task_registry.register(builder)

        # Synchronous notification on parent's sink (still alive during tool call)
        parent_sink = session_state.get("event_sink")
        if parent_sink:
            parent_sink.push("subworkflow_building", {
                "workflow_id": workflow_id,
                "name": workflow.name,
                "building": True,
            })

        # Inherit parent's build depth so nested creates are depth-limited.
        # No parent_sink reference passed — builder is fully independent.
        parent_depth = session_state.get("build_depth", 0)
        child_depth = parent_depth + 1

        thread = threading.Thread(
            target=_run_subworkflow_updater,
            args=(
                workflow_id, updater_prompt, repo_root, workflow_store,
                user_id, workflow.build_history, builder,
                child_depth,
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
