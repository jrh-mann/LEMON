"""Orchestrator for tool-based CLI use.

Single class that manages the LLM conversation loop:
  1. Build system prompt + user message
  2. Call LLM (optionally with tools)
  3. Execute tool calls, feed results back to LLM
  4. Repeat until LLM responds with text only
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import time
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from ..tools import ToolRegistry
from ..tools.constants import WORKFLOW_EDIT_TOOLS, WORKFLOW_INPUT_TOOLS, WORKFLOW_BOUND_TOOLS
from ..llm import call_llm
from .conversation_manager import ConversationManager
from .system_prompt import build_system_prompt
from ..tools.schema_gen import generate_all_schemas
from ..utils.cancellation import CancellationError
from ..validation.workflow_validator import WorkflowValidator
from ..events.bus import EventBus
from ..events.types import TOOL_STARTED, TOOL_COMPLETED, TOOL_BATCH_COMPLETE

if TYPE_CHECKING:
    from .turn import Turn

logger = logging.getLogger(__name__)

_MAX_FILE_BYTES = {"image": 4_500_000, "pdf": 32_000_000}
_MAX_TOOL_ITERATIONS = 50
_MAX_TOOL_MESSAGES = 200


@dataclass
class ToolResult:
    tool: str
    data: Dict[str, Any]
    success: bool
    message: str
    error: Optional[str] = None


class Orchestrator:
    """Minimal orchestrator that uses the LLM to choose tools."""

    _validator = WorkflowValidator()

    def __init__(self, tools: ToolRegistry, event_bus: Optional[EventBus] = None):
        self.tools = tools
        self.event_bus: EventBus = event_bus or EventBus()
        self.workflow: Dict[str, Any] = {
            "nodes": [], "edges": [], "variables": [], "outputs": [],
        }
        self.conversation = ConversationManager(context_limit=200_000)

        # Session context — set by ChatTask before calling respond()
        self.workflow_store: Optional[Any] = None
        self.user_id: Optional[str] = None
        self.current_workflow_id: Optional[str] = None
        self.current_workflow_name: Optional[str] = None
        self.open_tabs: List[Dict[str, Any]] = []
        self.uploaded_files: List[Dict[str, Any]] = []
        self._guidance: List[Dict[str, Any]] = []
        self.repo_root: Optional[Any] = None
        self.event_sink: Optional[Any] = None

    # --- Workflow state views (used by ChatTask, tools, tests) ---

    @property
    def current_workflow(self) -> Dict[str, Any]:
        return {"nodes": self.workflow.get("nodes", []), "edges": self.workflow.get("edges", [])}

    @current_workflow.setter
    def current_workflow(self, value: Dict[str, Any]) -> None:
        if isinstance(value, dict):
            for key in ("nodes", "edges"):
                if isinstance(value.get(key), list):
                    self.workflow[key] = value[key]

    @property
    def workflow_analysis(self) -> Dict[str, Any]:
        return {"variables": self.workflow.get("variables", []), "outputs": self.workflow.get("outputs", [])}

    @workflow_analysis.setter
    def workflow_analysis(self, value: Dict[str, Any]) -> None:
        if isinstance(value, dict):
            for key in ("variables", "outputs"):
                if isinstance(value.get(key), list):
                    self.workflow[key] = value[key]

    # --- Workflow sync ---

    def sync_workflow(self, provider: Optional[Callable[[], Dict[str, Any]]] = None) -> None:
        """Sync nodes/edges from an external source (e.g. conversation state)."""
        if provider is None:
            return
        try:
            self.current_workflow = provider()
        except Exception as exc:
            logger.error("Failed to sync workflow: %s", exc)

    def sync_workflow_analysis(self, provider: Optional[Callable[[], Dict[str, Any]]] = None) -> None:
        """Sync variables/outputs from an external source."""
        if provider is None:
            return
        try:
            self.workflow_analysis = provider()
        except Exception as exc:
            logger.error("Failed to sync workflow analysis: %s", exc)

    def refresh_workflow_from_db(self) -> None:
        """Reload full workflow state from DB after tool calls."""
        if not self.workflow_store or not self.current_workflow_id:
            return
        try:
            record = self.workflow_store.get_workflow(self.current_workflow_id, self.user_id)
        except Exception as exc:
            logger.error("refresh_workflow_from_db failed: %s", exc)
            return
        if not record:
            return
        self.workflow["nodes"] = record.nodes or []
        self.workflow["edges"] = record.edges or []
        self.workflow["variables"] = record.inputs or []
        self.workflow["outputs"] = record.outputs or []

    # --- Tool execution ---

    def run_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        *,
        stream: Optional[Callable[[str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
        on_thinking: Optional[Callable[[str], None]] = None,
    ) -> ToolResult:
        if tool_name in WORKFLOW_BOUND_TOOLS and self.current_workflow_id:
            args.setdefault("workflow_id", self.current_workflow_id)

        logger.info("Running tool name=%s args_keys=%s", tool_name, sorted(args.keys()))
        self.event_bus.emit(TOOL_STARTED, {"tool": tool_name, "args": args})

        data = self.tools.execute(
            tool_name, args,
            stream=stream, should_cancel=should_cancel,
            on_progress=on_progress, on_thinking=on_thinking,
            session_state={
                "current_workflow": self.current_workflow,
                "workflow_analysis": self.workflow_analysis,
                "current_workflow_id": self.current_workflow_id,
                "open_tabs": self.open_tabs,
                "uploaded_files": self.uploaded_files,
                "workflow_store": self.workflow_store,
                "user_id": self.user_id,
                "repo_root": self.repo_root,
                "event_sink": self.event_sink,
            },
        )
        result = _normalize_tool_result(tool_name, data)

        if result.success and tool_name in (WORKFLOW_EDIT_TOOLS | WORKFLOW_INPUT_TOOLS):
            self.refresh_workflow_from_db()
            if tool_name in WORKFLOW_EDIT_TOOLS:
                result = self._post_tool_validate(result)

        if result.success and tool_name == "extract_guidance":
            items = result.data.get("guidance")
            if isinstance(items, list):
                self._guidance = items

        self.event_bus.emit(TOOL_COMPLETED, {
            "tool": tool_name, "args": args,
            "result": result.data, "success": result.success,
        })
        return result

    def _post_tool_validate(self, result: ToolResult) -> ToolResult:
        """Non-strict validation after a workflow edit tool succeeds."""
        nodes = self.workflow.get("nodes", [])
        if not nodes:
            return result
        is_valid, errors = self._validator.validate(
            {"nodes": nodes, "edges": self.workflow.get("edges", []),
             "variables": self.workflow.get("variables", [])},
            strict=False,
        )
        if is_valid:
            return result
        error_text = "; ".join(f"[{e.code}] {e.message}" for e in errors)
        logger.warning("Post-tool validation failed (%d errors): %s", len(errors), error_text)
        return ToolResult(
            tool=result.tool,
            data={**result.data, "success": False, "error": error_text},
            success=False, message="",
            error=f"Workflow validation failed after tool execution: {error_text}",
        )

    # --- LLM conversation ---

    def respond(
        self,
        user_message: str,
        *,
        turn: Optional["Turn"] = None,
        has_files: Optional[List[Dict[str, Any]]] = None,
        stream: Optional[Callable[[str], None]] = None,
        allow_tools: bool = True,
        should_cancel: Optional[Callable[[], bool]] = None,
        on_tool_event: Optional[
            Callable[[str, str, Dict[str, Any], Optional[Dict[str, Any]]], None]
        ] = None,
        thinking: bool = False,
        on_thinking: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Run one conversation turn: user message → LLM → tools → response.

        When a Turn is provided, the orchestrator:
        - Records tool messages on the Turn (replaces turn_tool_messages)
        - Raises CancellationError on cancel (caller handles via turn.cancel())
        - Re-raises exceptions on error (caller handles via turn.fail())
        - Does NOT call save_turn/finalize_cancel/save_error (caller uses turn.commit())

        When turn=None, falls back to the legacy self-contained behavior.
        """
        new_files = has_files or []
        if new_files:
            self.uploaded_files = new_files

        # Cancellation helpers
        def is_cancelled() -> bool:
            return bool(should_cancel and should_cancel())

        did_stream = False
        streamed_chunks: List[str] = []

        def finalize_cancel() -> str:
            """Handle cancellation. With Turn: raises. Without: saves to history."""
            if turn:
                raise CancellationError("Turn cancelled by user")
            return self.conversation.finalize_cancel(user_message, streamed_chunks)

        def on_delta(delta: str) -> None:
            nonlocal did_stream
            if is_cancelled():
                return
            did_stream = True
            streamed_chunks.append(delta)
            if stream:
                stream(delta)

        tool_desc = generate_all_schemas(self.tools) if allow_tools else None
        system = build_system_prompt(
            has_files=self.uploaded_files, allow_tools=allow_tools,
            current_workflow_id=self.current_workflow_id,
            current_workflow_name=self.current_workflow_name,
            guidance=self._guidance or None,
        )
        self.conversation.compact_if_needed()
        effective_message = _build_user_content(user_message, new_files)
        messages = self.conversation.build_messages(system, effective_message)

        # --- Initial LLM call ---
        try:
            resp = call_llm(
                messages,
                tools=tool_desc, tool_choice=None if allow_tools else "none",
                on_delta=on_delta if stream else None,
                caller="orchestrator", request_tag="initial",
                should_cancel=should_cancel,
                thinking=thinking, on_thinking=on_thinking,
            )
            raw, tool_calls = resp.text, resp.tool_calls
            thinking_blocks = resp.thinking_blocks  # Preserve for tool loop replay
            if resp.usage:
                self.conversation.update_token_estimate(resp.usage.get("input_tokens", 0))
            if is_cancelled():
                return finalize_cancel()
        except CancellationError:
            return finalize_cancel()
        except Exception as exc:
            logger.exception("LLM error while responding")
            if turn:
                raise  # Caller handles via turn.fail()
            self.conversation.save_error(user_message, f"LLM error: {exc}")
            return f"LLM error: {exc}"

        # --- Tool loop ---
        tool_results: List[ToolResult] = []
        # turn_tool_messages: only used when turn=None (legacy path)
        turn_tool_messages: List[Dict[str, Any]] = []
        asked_question = False
        iterations = 0

        while allow_tools and tool_calls:
            if is_cancelled():
                return finalize_cancel()
            iterations += 1
            if iterations > _MAX_TOOL_ITERATIONS:
                logger.error("Max tool iterations. Tools: %s", [r.tool for r in tool_results])
                if turn:
                    raise CancellationError(f"Max tool iterations ({_MAX_TOOL_ITERATIONS})")
                self.conversation.save_error(user_message, f"Max tool iterations ({_MAX_TOOL_ITERATIONS}).")
                return finalize_cancel()

            # Transition: CALLING_LLM → EXECUTING_TOOLS
            if turn:
                turn.begin_tool_execution()

            # In-flight message includes thinking blocks for API replay
            asst_msg = {"role": "assistant", "content": raw or "", "tool_calls": tool_calls}
            if thinking_blocks:
                asst_msg["thinking_blocks"] = thinking_blocks
            messages.append(asst_msg)

            # Persisted message strips thinking (ephemeral for tool loop only)
            persist_msg = {"role": "assistant", "content": raw or "", "tool_calls": tool_calls}
            if turn:
                turn.add_assistant_tool_use(persist_msg)
            else:
                turn_tool_messages.append(persist_msg)

            # Execute each tool in the batch
            tool_failure = None
            skipped_calls: List[Dict[str, Any]] = []
            for idx, tc in enumerate(tool_calls):
                if is_cancelled():
                    return finalize_cancel()

                # Tool calls are native Anthropic format: {id, name, input: dict}
                tool_name = tc.get("name")
                args = tc.get("input") or {}

                try:
                    if on_tool_event:
                        on_tool_event("tool_start", tool_name, args, None)

                    tool_start = time.perf_counter()
                    result = self.run_tool(
                        tool_name, args, stream=None, should_cancel=should_cancel,
                        on_progress=lambda s, n=tool_name: on_tool_event and on_tool_event("tool_progress", n, {"status": s}, None),
                        on_thinking=lambda c, n=tool_name: on_tool_event and on_tool_event("tool_thinking", n, {"chunk": c}, None),
                    )
                    duration_ms = (time.perf_counter() - tool_start) * 1000
                    tool_results.append(result)

                    # Image blocks pass through directly; otherwise json.dumps
                    raw_content = result.data.get("content")
                    tool_content = raw_content if isinstance(raw_content, list) else json.dumps(result.data)
                    # Native Anthropic format: tool results are user messages
                    # with tool_result content blocks
                    tool_msg = {
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": tc.get("id"),
                            "content": tool_content,
                        }],
                    }
                    messages.append(tool_msg)

                    if turn:
                        turn.add_tool_result(
                            tc.get("id"), tool_name, args, result.data,
                            success=result.success, duration_ms=duration_ms,
                            content=tool_content,
                        )
                    else:
                        turn_tool_messages.append(tool_msg)

                    if on_tool_event:
                        on_tool_event("tool_complete", tool_name, args, result.data)

                    if tool_name == "ask_question" and result.success:
                        asked_question = True
                        break
                    if not result.success:
                        tool_failure = result
                        skipped_calls = tool_calls[idx + 1:]
                        break
                except CancellationError:
                    return finalize_cancel()
                except Exception as exc:
                    logger.error("tool_error name=%s error=%s", tool_name, exc, exc_info=True)
                    if turn:
                        raise  # Caller handles via turn.fail()
                    self.conversation.save_error(user_message, f"Tool error ({tool_name}): {exc}")
                    return f"Tool error ({tool_name}): {exc}"

            # Inject skipped-tool placeholders
            for skipped in skipped_calls:
                sname = skipped.get("name")
                sargs = skipped.get("input") or {}
                sp = {"success": False, "skipped": True, "error": f"Skipped {sname} — previous tool failed."}
                skip_msg = {
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": skipped.get("id"),
                        "content": json.dumps(sp),
                    }],
                }
                messages.append(skip_msg)
                if turn:
                    turn.add_skipped_tool(skipped.get("id"), sname, sargs)
                else:
                    turn_tool_messages.append(skip_msg)
                if on_tool_event:
                    on_tool_event("tool_complete", sname, sargs, sp)

            if on_tool_event:
                on_tool_event("tool_batch_complete", "", {}, None)
            self.event_bus.emit(TOOL_BATCH_COMPLETE, {})

            if asked_question or is_cancelled():
                break

            # Trim messages if too large
            if len(messages) > _MAX_TOOL_MESSAGES:
                logger.info("Tool loop messages trimmed from %d to %d", len(messages), _MAX_TOOL_MESSAGES)
                messages[:] = [messages[0]] + messages[-(_MAX_TOOL_MESSAGES - 1):]

            # Transition: EXECUTING_TOOLS → CALLING_LLM
            if turn:
                turn.begin_llm_call()

            # Next LLM call
            try:
                resp = call_llm(
                    messages, tools=tool_desc,
                    on_delta=on_delta if stream else None,
                    caller="orchestrator", request_tag="post_tool",
                    should_cancel=should_cancel,
                    thinking=thinking, on_thinking=on_thinking,
                )
                raw, tool_calls = resp.text, resp.tool_calls
                thinking_blocks = resp.thinking_blocks
                self.conversation.update_token_estimate(resp.usage.get("input_tokens", 0))
            except CancellationError:
                return finalize_cancel()
            if is_cancelled():
                return finalize_cancel()

        # --- Assemble final response ---
        if asked_question:
            final_text = raw or ""
        else:
            final_text = raw or (_summarize(tool_results) if tool_results else "")
            if tool_results and not final_text.strip():
                final_text = f"Completed {len(tool_results)} tool operation(s)."
            if not final_text.strip():
                final_text = "I wasn't able to generate a response. Could you rephrase or provide more details?"

        if stream and final_text and not did_stream:
            for i in range(0, len(final_text), 800):
                stream(final_text[i:i + 800])

        # Persist turn to history — when Turn is active, caller handles via turn.commit()
        if not turn:
            self.conversation.save_turn(
                user_message, final_text,
                tool_messages=turn_tool_messages or None,
            )
        return final_text


# --- Module helpers ---


def _build_user_content(user_message: str, files: List[Dict[str, Any]]) -> Any:
    """Build LLM message content, injecting base64 files for new uploads."""
    if not files:
        return user_message
    blocks: List[Dict[str, Any]] = []
    for f in files:
        block = _encode_file(f)
        if block:
            blocks.append(block)
    if not blocks:
        return user_message
    blocks.append({"type": "text", "text": user_message})
    return blocks


def _encode_file(file_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Encode an image or PDF as a base64 content block."""
    file_type = file_info.get("file_type", "")
    path = Path(file_info.get("path", ""))
    if not path.exists():
        logger.warning("File not found: %s", path)
        return None
    raw = path.read_bytes()
    max_bytes = _MAX_FILE_BYTES.get(file_type, 0)
    if max_bytes and len(raw) > max_bytes:
        logger.warning("File %s too large (%d bytes), skipping", path.name, len(raw))
        return None
    b64 = base64.b64encode(raw).decode()
    if file_type == "image":
        suffix = path.suffix.lower()
        media = "image/jpeg" if suffix in (".jpg", ".jpeg") else f"image/{suffix.lstrip('.')}"
        return {"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}}
    elif file_type == "pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    return None


def _normalize_tool_result(tool_name: str, data: Any) -> ToolResult:
    if not isinstance(data, dict):
        data = {"result": data}
    success = data.get("success")
    if success is None:
        success = "error" not in data
        data["success"] = bool(success)
    success = bool(success)
    message = data.get("message", "") if isinstance(data.get("message"), str) else ""
    error = data.get("error", "") if isinstance(data.get("error"), str) else ""
    if not success and not error:
        error = message or f"Tool {tool_name} failed."
    return ToolResult(
        tool=tool_name, data=data, success=success,
        message=message, error=error if not success else None,
    )


def _summarize(results: List[ToolResult]) -> str:
    parts = []
    for r in results:
        if isinstance(r.data, dict) and r.data.get("skipped"):
            continue
        if not r.success:
            parts.append(f"Tool failed ({r.tool}): {r.error or r.message or 'failed'}")
        elif r.message:
            parts.append(r.message)
    return "\n\n".join(parts)
