"""Chat turn runner — executes one orchestrator turn with full lifecycle.

Extracted from ChatTask.run(). Handles Turn creation, orchestrator.respond(),
and Turn completion/cancellation/failure. Returns a TurnResult so the caller
(ChatTask) can emit the appropriate SSE events without managing Turn internals.

Uses ChatRuntimePorts for dependency injection — no direct reference to
ChatTask, ChatEventChannel, or ToolEventProjector.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import anthropic

from .conversations import Conversation
from ..agents.turn import Turn, TurnStatus
from ..storage.conversation_log import ConversationLogger
from ..utils.cancellation import CancellationError

logger = logging.getLogger("backend.api")


@dataclass(frozen=True)
class ChatRuntimePorts:
    """Explicit hooks wired by ChatTask to channel, projector, orchestrator.

    Keeps run_turn decoupled from concrete implementations — all side effects
    (streaming, tool events, cancellation) go through these callables.
    """

    stream_chunk: Callable[[str], None]
    stream_thinking: Callable[[str], None]
    on_tool_event: Callable
    is_cancelled: Callable[[], bool]
    # For reading accumulated stream text (needed to persist partial on cancel)
    get_stream_buffer: Callable[[], str]
    conversation_logger: Optional[ConversationLogger] = None


@dataclass
class TurnResult:
    """Outcome of a single orchestrator turn.

    Carries enough information for ChatTask to emit SSE events and
    update state without needing the Turn object itself.
    """

    response_text: str
    status: TurnStatus
    cancelled: bool = False
    error: Optional[Exception] = None
    # Context window usage — emitted as context_status event
    input_tokens: int = 0
    output_tokens: int = 0
    context_usage_pct: float = 0.0
    message_count: int = 0


def run_turn(
    *,
    convo: Conversation,
    message: str,
    task_id: str,
    user_id: str,
    workflow_id: Optional[str],
    saved_file_paths: List[Dict[str, Any]],
    ports: ChatRuntimePorts,
) -> TurnResult:
    """Execute one orchestrator turn with full Turn lifecycle management.

    Creates a Turn, calls orchestrator.respond(), and handles success,
    cancellation, and failure. Does NOT emit SSE events — the caller
    uses the returned TurnResult for that.

    Raises nothing — all exceptions are caught and reflected in TurnResult.
    """
    turn = Turn(
        message, convo.id,
        conversation_logger=ports.conversation_logger,
        task_id=task_id,
    )

    # Ensure conversation row exists in audit DB before Turn.start()
    if ports.conversation_logger:
        try:
            ports.conversation_logger.ensure_conversation(
                convo.id,
                user_id=user_id,
                workflow_id=workflow_id,
                model="claude-sonnet-4-6",
            )
        except Exception:
            logger.error(
                "Failed to ensure conversation in audit DB: conv=%s",
                convo.id, exc_info=True,
            )

    # File metadata for audit log
    file_meta = [
        {"name": f.get("name"), "file_type": f.get("file_type")}
        for f in saved_file_paths
    ] if saved_file_paths else None
    turn.start(file_meta=file_meta)

    try:
        response_text = convo.orchestrator.respond(
            message,
            turn=turn,
            has_files=saved_file_paths if saved_file_paths else [],
            stream=ports.stream_chunk,
            allow_tools=True,
            should_cancel=ports.is_cancelled,
            on_tool_event=ports.on_tool_event,
            thinking=True,
            on_thinking=ports.stream_thinking,
        )

        # Turn completed successfully
        orch = convo.orchestrator
        turn.complete(
            response_text,
            input_tokens=orch.conversation._last_input_tokens or 0,
            output_tokens=getattr(orch, "_last_output_tokens", None) or 0,
        )
        turn.commit(orch.conversation)

        return TurnResult(
            response_text=response_text,
            status=TurnStatus.COMPLETED,
            input_tokens=orch.conversation._last_input_tokens or 0,
            output_tokens=getattr(orch, "_last_output_tokens", None) or 0,
            context_usage_pct=orch.conversation.context_usage_pct,
            message_count=len(orch.conversation.history),
        )

    except CancellationError:
        if turn.status not in (TurnStatus.COMPLETED, TurnStatus.CANCELLED, TurnStatus.FAILED):
            stream_buf = ports.get_stream_buffer()
            turn.cancel([stream_buf] if stream_buf else [])
            turn.commit(convo.orchestrator.conversation)
        return TurnResult(
            response_text=turn.partial_text or "",
            status=TurnStatus.CANCELLED,
            cancelled=True,
        )

    except Exception as exc:
        logger.exception("Chat turn failed: task=%s", task_id)
        if turn.status not in (TurnStatus.COMPLETED, TurnStatus.CANCELLED, TurnStatus.FAILED):
            turn.fail(str(exc))
            turn.commit(convo.orchestrator.conversation)
        return TurnResult(
            response_text="",
            status=TurnStatus.FAILED,
            error=exc,
        )
