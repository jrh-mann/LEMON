"""Tool for creating a subworkflow and spawning a background orchestrator to build it.

The main orchestrator calls this tool when it encounters a subprocess node that needs
a new subworkflow. The tool:
1. Creates a workflow in the DB immediately (returning workflow_id)
2. Registers any declared input variables
3. Spawns a background thread with a fresh Orchestrator to build the subworkflow
4. Returns immediately so the main orchestrator can continue in parallel
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List
from uuid import uuid4

from ..core import Tool, ToolParameter, extract_session_deps
from ..constants import (
    generate_workflow_id,
    VALID_WORKFLOW_OUTPUT_TYPES,
    builder_semaphore,
    MAX_BUILD_HISTORY_MESSAGES,
)

logger = logging.getLogger(__name__)


def _run_subworkflow_builder(
    workflow_id: str,
    brief: str,
    repo_root: Any,
    workflow_store: Any,
    user_id: str,
    sink: Any,
) -> None:
    """Background thread: build a subworkflow using a fresh orchestrator.

    Args:
        workflow_id: ID of the workflow to build into
        brief: Detailed description of what the subworkflow should do
        repo_root: Path to repo root for tool construction
        workflow_store: WorkflowStore instance for DB access
        user_id: Owner user ID
        sink: EventSink for emitting SSE events to the parent chat stream
    """
    # Import here to avoid circular imports (builder_callbacks → tools.constants → tools → this file)
    from ...api.builder_callbacks import BackgroundBuilderCallbacks
    from ...api.task_registry import task_registry as _task_registry

    # Set up unified callbacks — emits same chat_* events as main orchestrator,
    # tagged with workflow_id so frontend routes them to chatStore.conversations[workflow_id]
    bg_task_id = f"bg_{uuid4().hex[:8]}"
    cb = BackgroundBuilderCallbacks(
        sink, workflow_id,
        user_id=user_id, task_id=bg_task_id,
    )
    response_text = ""

    # Register as active task so handle_resume_task can reconnect after refresh.
    # BackgroundBuilderCallbacks exposes the same interface as WsChatTask
    # (done, conn_id, thinking_chunks, stream_buffer, task_id, current_workflow_id, user_id).
    _task_registry.register(cb)

    # Acquire semaphore to limit concurrent builder threads
    with builder_semaphore:
        try:
            # Import here to avoid circular imports
            from ...agents.orchestrator_factory import build_orchestrator

            orchestrator = build_orchestrator(repo_root)
            orchestrator.workflow_store = workflow_store
            orchestrator.user_id = user_id
            orchestrator.current_workflow_id = workflow_id
            # Pass full context so the background builder can emit progress events
            # and spawn nested subworkflows (which need repo_root to build_orchestrator)
            orchestrator.repo_root = repo_root
            orchestrator.event_sink = sink

            logger.info(
                "Background builder started for subworkflow %s: %s",
                workflow_id, brief[:100],
            )

            # Emit the brief as a user message so the frontend shows it during streaming
            cb.emit_user_message(brief)
            cb.emit_progress("Building workflow...", event="start")

            # Run the orchestrator with the brief — it will use its tools to build
            # the subworkflow autonomously (add_node, add_connection, etc.)
            # Uses the same callback pattern as SocketChatTask.run()
            # Turn wraps the build turn — no audit logger for background builds
            from ...agents.turn import Turn
            build_turn = Turn(brief, f"bg_{workflow_id}")
            build_turn.start()
            try:
                response_text = orchestrator.respond(
                    brief, turn=build_turn, allow_tools=True,
                    stream=cb.stream_chunk,
                    on_tool_event=cb.on_tool_event,
                    should_cancel=cb.is_cancelled,
                    thinking=True,
                    on_thinking=cb.stream_thinking,
                )
                build_turn.complete(response_text)
            except Exception as build_exc:
                build_turn.fail(str(build_exc))
                raise
            finally:
                build_turn.commit(orchestrator.conversation)

            # Save the workflow to library and persist the builder's conversation
            # history so the user can see how it was built and resume later.
            # Cap history to prevent unbounded DB blob growth.
            build_hist = orchestrator.conversation.history
            if len(build_hist) > MAX_BUILD_HISTORY_MESSAGES:
                build_hist = build_hist[-MAX_BUILD_HISTORY_MESSAGES:]
            workflow_store.update_workflow(
                workflow_id, user_id,
                is_draft=False,
                building=False,
                build_history=build_hist,
            )

            logger.info("Background builder finished for subworkflow %s", workflow_id)

        except Exception as exc:
            logger.error(
                "Background builder FAILED for subworkflow %s: %s",
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
            if sink:
                sink.push("build_error", {
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
            if sink:
                sink.push("subworkflow_ready", {"workflow_id": workflow_id})


class CreateSubworkflowTool(Tool):
    """Create a subworkflow and spawn a background orchestrator to build it.

    This tool is used by the main orchestrator when it needs a subprocess node
    that references a subworkflow. It creates the workflow record in the DB
    immediately and returns the workflow_id so the caller can wire up the
    subprocess node. A background thread then builds out the subworkflow's
    nodes and connections autonomously.
    """

    name = "create_subworkflow"
    description = (
        "Create a subworkflow and build it in the background. Returns a workflow_id "
        "that you can use as the subworkflow_id in a subprocess node. "
        "A background orchestrator builds the subworkflow's nodes and connections "
        "autonomously using your brief. FIRST check list_workflows_in_library to "
        "see if a suitable workflow already exists before calling this."
    )
    parameters = [
        ToolParameter(
            "name", "string",
            "Name for the subworkflow (e.g., 'BMI Calculator', 'Credit Score Assessment')",
            required=True,
        ),
        ToolParameter(
            "output_type", "string",
            "Type of value the subworkflow returns",
            required=True,
            enum=["string", "number", "bool", "json"],
        ),
        ToolParameter(
            "brief", "string",
            (
                "Detailed description of the subworkflow's logic. Include: "
                "what it calculates/decides, step-by-step decision logic, "
                "all inputs with types, expected output meaning. More detail = better result."
            ),
            required=True,
        ),
        ToolParameter(
            "inputs", "array",
            "Input variables the subworkflow expects",
            required=True,
            items={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Input variable name",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["string", "number", "bool", "json"],
                        "description": "Input variable type",
                    },
                    "description": {
                        "type": "string",
                        "description": "What this input represents",
                    },
                },
                "required": ["name", "type"],
            },
        ),
    ]

    def execute(self, args: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        # --- Validate parameters ---
        name = args.get("name")
        if not name or not isinstance(name, str) or not name.strip():
            return {
                "success": False,
                "error": "'name' is required and must be a non-empty string",
                "error_code": "MISSING_NAME",
            }

        output_type = args.get("output_type")
        if not output_type or output_type not in VALID_WORKFLOW_OUTPUT_TYPES:
            return {
                "success": False,
                "error": f"'output_type' must be one of: {', '.join(sorted(VALID_WORKFLOW_OUTPUT_TYPES))}",
                "error_code": "INVALID_OUTPUT_TYPE",
            }

        brief = args.get("brief")
        if not brief or not isinstance(brief, str) or not brief.strip():
            return {
                "success": False,
                "error": "'brief' is required and must be a non-empty string",
                "error_code": "MISSING_BRIEF",
            }

        inputs = args.get("inputs")
        if not isinstance(inputs, list):
            return {
                "success": False,
                "error": "'inputs' must be an array of {name, type, description} objects",
                "error_code": "INVALID_INPUTS",
            }

        # --- Extract session dependencies ---
        session_state, workflow_store, user_id, err = extract_session_deps(
            kwargs, action="create subworkflow",
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

        # --- Create the workflow in DB ---
        workflow_id = generate_workflow_id()
        name_clean = name.strip()

        try:
            workflow_store.create_workflow(
                workflow_id=workflow_id,
                user_id=user_id,
                name=name_clean,
                description=brief.strip()[:500],  # First 500 chars as description
                output_type=output_type,
                is_draft=False,
                building=True,  # Mark as building until background thread finishes
            )
        except Exception as exc:
            return {
                "success": False,
                "error": f"Failed to create subworkflow in DB: {exc}",
                "error_code": "CREATE_FAILED",
            }

        # --- Register input variables via the add_workflow_variable tool ---
        from ..workflow_input import AddWorkflowVariableTool
        add_var_tool = AddWorkflowVariableTool()

        registered_inputs: List[Dict[str, str]] = []
        for inp in inputs:
            if not isinstance(inp, dict) or "name" not in inp:
                continue
            var_result = add_var_tool.execute(
                {
                    "workflow_id": workflow_id,
                    "name": inp["name"],
                    "type": inp.get("type", "string"),
                    "description": inp.get("description", ""),
                },
                session_state=session_state,
            )
            if var_result.get("success"):
                registered_inputs.append({
                    "name": inp["name"],
                    "type": inp.get("type", "string"),
                    "variable_id": var_result.get("variable_id", ""),
                })
            else:
                logger.warning(
                    "Failed to register input variable '%s' for subworkflow %s: %s",
                    inp.get("name"), workflow_id, var_result.get("error"),
                )

        # --- Build a detailed prompt for the background orchestrator ---
        input_desc = "\n".join(
            f"  - {inp['name']} ({inp.get('type', 'string')}): {inp.get('description', '')}"
            for inp in inputs if isinstance(inp, dict) and "name" in inp
        )
        builder_prompt = (
            f"You are building a subworkflow called '{name_clean}'.\n"
            f"Output type: {output_type}\n\n"
            f"Input variables (already registered):\n{input_desc}\n\n"
            f"Requirements:\n{brief.strip()}\n\n"
            f"The workflow ID is {workflow_id}. Use this workflow_id in all tool calls.\n"
            f"Build this workflow completely: add all necessary nodes and connections.\n"
            f"When done, call set_workflow_output to declare the output."
        )

        # --- Spawn background builder thread ---
        sink = session_state.get("event_sink")

        # Notify frontend that a new subworkflow was created so the library
        # page can auto-refresh and show the "Building..." badge
        if sink:
            sink.push("subworkflow_created", {
                "workflow_id": workflow_id,
                "name": name_clean,
                "building": True,
            })

        thread = threading.Thread(
            target=_run_subworkflow_builder,
            args=(workflow_id, builder_prompt, repo_root, workflow_store, user_id, sink),
            daemon=True,
            name=f"subworkflow-builder-{workflow_id}",
        )
        thread.start()

        logger.info(
            "Created subworkflow %s ('%s') and spawned background builder",
            workflow_id, name_clean,
        )

        return {
            "success": True,
            "workflow_id": workflow_id,
            "name": name_clean,
            "output_type": output_type,
            "status": "building",
            "registered_inputs": registered_inputs,
            "message": (
                f"Subworkflow '{name_clean}' created with ID {workflow_id}. "
                f"It is being built in the background. You can now use this workflow_id "
                f"as the subworkflow_id in a subprocess node."
            ),
        }
