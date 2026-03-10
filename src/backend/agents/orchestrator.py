"""Orchestrator for tool-based CLI use."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..tools import ToolRegistry
from ..tools.constants import WORKFLOW_EDIT_TOOLS, WORKFLOW_INPUT_TOOLS, WORKFLOW_BOUND_TOOLS
from ..llm import call_llm_stream, call_llm_with_tools
from .system_prompt import build_system_prompt
from ..tools.schema_gen import generate_all_schemas
from ..utils.cancellation import CancellationError
from ..validation.workflow_validator import WorkflowValidator


@dataclass
class ToolResult:
    tool: str
    data: Dict[str, Any]
    success: bool
    message: str
    error: Optional[str] = None


class Orchestrator:
    """Minimal orchestrator that uses the LLM to choose tools."""

    def __init__(self, tools: ToolRegistry):
        self.tools = tools

        # Single canonical workflow dict (nodes + edges + variables + outputs)
        self.workflow: Dict[str, Any] = {
            "nodes": [],
            "edges": [],
            "variables": [],
            "outputs": [],
        }

        self.history: List[Dict[str, str]] = []
        self._logger = logging.getLogger(__name__)
        self._tool_logger = logging.getLogger("backend.tool_calls")

        # Session context for tools (workflow_store, user_id)
        self.workflow_store: Optional[Any] = None
        self.user_id: Optional[str] = None
        # ID and name of current workflow on canvas (None if unsaved/new)
        self.current_workflow_id: Optional[str] = None
        self.current_workflow_name: Optional[str] = None
        # All open tabs with workflows (for list_workflows_in_library to show drafts)
        self.open_tabs: List[Dict[str, Any]] = []
        # Files uploaded by the user — persisted across turns for tool access (e.g. view_image)
        self.uploaded_files: List[Dict[str, Any]] = []
        # Guidance notes extracted from uploaded images by extract_guidance tool.
        # Persisted across turns so that build_system_prompt() can inject them
        # even after history truncation drops the original tool_result message.
        self._guidance: List[Dict[str, Any]] = []
        # Repo root path — needed for background subworkflow builders
        self.repo_root: Optional[Any] = None
        # WebSocket registry and connection ID — for emitting events from background threads
        self.ws_registry: Optional[Any] = None
        self.conn_id: Optional[str] = None

        # Context window tracking — updated after each LLM call with actual token counts
        self._last_input_tokens: int = 0
        self._context_limit: int = 200_000  # Claude models have 200k context window

        # Optional conversation logger for audit trail (injected by ws_chat)
        self._conversation_logger: Optional[Any] = None
        self._conversation_id: Optional[str] = None

    @property
    def context_usage_pct(self) -> int:
        """Percentage of context window used by the last LLM call."""
        if not self._last_input_tokens:
            return 0
        return min(100, int(self._last_input_tokens / self._context_limit * 100))

    # --- Conversation compaction ---
    # When the context window fills up, summarize older history to free space
    # while preserving key decisions and context (similar to Claude Code).

    _COMPACTION_THRESHOLD_PCT = 70   # Compact when input tokens > 70% of context
    _CHARS_PER_TOKEN = 4             # Rough estimate for pre-flight token counting

    def _estimate_history_tokens(self) -> int:
        """Rough token estimate from history character counts."""
        total_chars = sum(len(str(m.get("content", ""))) for m in self.history)
        return total_chars // self._CHARS_PER_TOKEN

    def _needs_compaction(self) -> bool:
        """Check if history should be compacted before the next LLM call."""
        # Use actual token count from last API call if available
        if self._last_input_tokens > 0:
            return self._last_input_tokens > self._context_limit * self._COMPACTION_THRESHOLD_PCT / 100
        # Fallback: estimate from history size (only triggers for very long histories)
        return self._estimate_history_tokens() > self._context_limit * self._COMPACTION_THRESHOLD_PCT / 100

    def _compact_history_if_needed(self) -> None:
        """Summarize older history messages if context window is filling up."""
        if not self._needs_compaction():
            return
        if len(self.history) < 6:
            return  # Too few messages to compact

        # Keep the most recent 1/3 of messages (minimum 4)
        keep_count = max(4, len(self.history) // 3)
        old_messages = self.history[:-keep_count]
        recent_messages = self.history[-keep_count:]

        # Log discarded messages to the audit trail before compaction
        if self._conversation_logger and self._conversation_id:
            try:
                self._conversation_logger.log_compaction(
                    self._conversation_id,
                    original_count=len(self.history),
                    summary="[pending]",
                    discarded_messages=old_messages,
                )
            except Exception:
                self._logger.debug("Failed to log compaction to audit trail", exc_info=True)

        # Build a text representation of old messages for the summarizer
        summary_parts = []
        for msg in old_messages:
            role = msg.get("role", "unknown")
            content = str(msg.get("content", ""))
            # Truncate very long individual messages for the summary prompt
            if len(content) > 500:
                content = content[:500] + "..."
            summary_parts.append(f"[{role}]: {content}")
        conversation_text = "\n".join(summary_parts)

        try:
            from ..llm.client import call_llm
            summary = call_llm(
                [
                    {"role": "system", "content": (
                        "Summarize this conversation history concisely. "
                        "Preserve: key decisions made, workflow changes (nodes/connections added/modified/deleted), "
                        "errors encountered, current state of the workflow, and any pending user requests. "
                        "Be brief but complete — this summary replaces the original messages."
                    )},
                    {"role": "user", "content": conversation_text},
                ],
                max_completion_tokens=2000,
                caller="orchestrator",
                request_tag="compaction",
            )
            # Replace history with summary + recent messages
            original_len = len(self.history)
            self.history = [
                {"role": "user", "content": f"[Conversation summary — {len(old_messages)} earlier messages]\n{summary}"},
                {"role": "assistant", "content": "Understood. I have the context from our earlier conversation."},
                *recent_messages,
            ]
            self._logger.info(
                "Compacted history: %d messages → summary + %d recent = %d total",
                original_len, len(recent_messages), len(self.history),
            )
        except Exception as exc:
            # Fallback: hard truncation if compaction LLM call fails
            self._logger.warning("Compaction LLM call failed (%s), falling back to truncation", exc)
            self.history = self.history[-50:]

    @property
    def current_workflow(self) -> Dict[str, Any]:
        """View of workflow structure (nodes/edges only) for session_state."""
        return {
            "nodes": self.workflow.get("nodes", []),
            "edges": self.workflow.get("edges", [])
        }

    @current_workflow.setter
    def current_workflow(self, value: Dict[str, Any]) -> None:
        if not isinstance(value, dict):
            return
        nodes = value.get("nodes", [])
        edges = value.get("edges", [])
        if isinstance(nodes, list):
            self.workflow["nodes"] = nodes
        if isinstance(edges, list):
            self.workflow["edges"] = edges

    @property
    def workflow_analysis(self) -> Dict[str, Any]:
        """View of workflow metadata (variables/outputs) for tools."""
        return {
            "variables": self.workflow.get("variables", []),
            "outputs": self.workflow.get("outputs", []),
        }

    @workflow_analysis.setter
    def workflow_analysis(self, value: Dict[str, Any]) -> None:
        """Set workflow metadata from dict."""
        if not isinstance(value, dict):
            return
        variables = value.get("variables", [])
        outputs = value.get("outputs", [])
        if isinstance(variables, list):
            self.workflow["variables"] = variables
        if isinstance(outputs, list):
            self.workflow["outputs"] = outputs

    def sync_workflow(
        self,
        workflow_provider: Optional[Callable[[], Dict[str, Any]]] = None
    ) -> None:
        """Sync workflow structure (nodes/edges) from external source.

        Args:
            workflow_provider: Callable that returns current workflow state.
                              None = use existing memory state (no-op).

        Design: Uses dependency injection to decouple from storage.
                Caller controls WHERE state comes from.
        """
        if workflow_provider is None:
            return  # No sync needed

        try:
            workflow_data = workflow_provider()
        except Exception as exc:
            self._logger.error("Failed to sync workflow: %s", exc)
            return

        if not isinstance(workflow_data, dict):
            return

        nodes = workflow_data.get("nodes", [])
        edges = workflow_data.get("edges", [])

        if isinstance(nodes, list) and isinstance(edges, list):
            # Update the unified workflow dict
            self.workflow["nodes"] = nodes
            self.workflow["edges"] = edges
            self._logger.info(
                "Synced workflow: %d nodes, %d edges",
                len(nodes),
                len(edges)
            )

    def refresh_workflow_from_db(self) -> None:
        """Reload workflow state from database after tool calls.

        Tools already load from DB, modify, and save back. This method
        reads the persisted state so the orchestrator's in-memory cache
        matches what tools wrote, eliminating manual per-tool sync code.
        """
        if not self.workflow_store or not self.current_workflow_id:
            return
        try:
            record = self.workflow_store.get_workflow(
                self.current_workflow_id, self.user_id
            )
        except Exception as exc:
            self._logger.error("refresh_workflow_from_db failed: %s", exc)
            return
        if not record:
            return
        # WorkflowRecord uses 'inputs' for variables (DB column name).
        self.workflow["nodes"] = record.nodes or []
        self.workflow["edges"] = record.edges or []
        self.workflow["variables"] = record.inputs or []
        self.workflow["outputs"] = record.outputs or []

    def sync_workflow_analysis(
        self,
        analysis_provider: Optional[Callable[[], Dict[str, Any]]] = None
    ) -> None:
        """Sync workflow metadata (variables/outputs) from external source.

        Args:
            analysis_provider: Callable that returns workflow analysis with 'variables' key.
                              None = use existing memory state (no-op).
        """
        if analysis_provider is None:
            return

        try:
            analysis_data = analysis_provider()
        except Exception as exc:
            self._logger.error("Failed to sync workflow analysis: %s", exc)
            return

        if not isinstance(analysis_data, dict):
            return

        variables = analysis_data.get("variables", [])
        outputs = analysis_data.get("outputs", [])

        if isinstance(variables, list) and isinstance(outputs, list):
            self.workflow["variables"] = variables
            self.workflow["outputs"] = outputs
            self._logger.info(
                "Synced workflow analysis: %d variables, %d outputs",
                len(variables),
                len(outputs)
            )

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
        # Auto-inject workflow_id for bound tools so the LLM doesn't need to pass it.
        if tool_name in WORKFLOW_BOUND_TOOLS and self.current_workflow_id:
            args.setdefault("workflow_id", self.current_workflow_id)

        self._logger.info("Running tool name=%s args_keys=%s", tool_name, sorted(args.keys()))
        self._tool_logger.info(
            "tool_request name=%s args=%s",
            tool_name,
            json.dumps(args, ensure_ascii=True),
        )

        # Direct in-process tool execution
        session_state = {
            "current_workflow": self.current_workflow,
            "workflow_analysis": self.workflow_analysis,
            "current_workflow_id": self.current_workflow_id,  # ID of workflow on canvas
            "open_tabs": self.open_tabs,  # All open tabs for list_workflows_in_library
            "uploaded_files": getattr(self, "uploaded_files", []),
        }
        # Add workflow_store and user_id if available
        if self.workflow_store is not None:
            session_state["workflow_store"] = self.workflow_store
        if self.user_id is not None:
            session_state["user_id"] = self.user_id
        # Pass repo_root, ws_registry, conn_id for background subworkflow builders
        if self.repo_root is not None:
            session_state["repo_root"] = self.repo_root
        if self.ws_registry is not None:
            session_state["ws_registry"] = self.ws_registry
        if self.conn_id is not None:
            session_state["conn_id"] = self.conn_id

        data = self.tools.execute(
            tool_name,
            args,
            stream=stream,
            should_cancel=should_cancel,
            on_progress=on_progress,
            on_thinking=on_thinking,
            session_state=session_state,
        )
        result = self._normalize_tool_result(tool_name, data)
        self._tool_logger.info(
            "tool_response name=%s data=%s",
            tool_name,
            json.dumps(result.data, ensure_ascii=True),
        )

        # Refresh in-memory state from DB after any tool that modifies the workflow.
        # Tools already save to DB; this replaces 100+ lines of manual per-tool sync.
        if result.success and tool_name in (WORKFLOW_EDIT_TOOLS | WORKFLOW_INPUT_TOOLS):
            self.refresh_workflow_from_db()

            # Post-tool structural validation for edit tools (non-strict: workflow
            # is still being built). Hard-fail so the LLM sees the error and can
            # call corrective tools.
            if tool_name in WORKFLOW_EDIT_TOOLS:
                result = self._post_tool_validate(result)


        # Persist guidance notes from extract_guidance so they survive history
        # truncation and remain available in the system prompt for later turns.
        if result.success and tool_name == "extract_guidance":
            guidance_items = result.data.get("guidance")
            if isinstance(guidance_items, list):
                self._guidance = guidance_items

        return result

    def _normalize_tool_result(self, tool_name: str, data: Any) -> ToolResult:
        if not isinstance(data, dict):
            data = {"result": data}
        success = data.get("success")
        if success is None:
            success = "error" not in data
            data["success"] = bool(success)
        success = bool(success)
        message = data.get("message") if isinstance(data.get("message"), str) else ""
        error = data.get("error") if isinstance(data.get("error"), str) else ""
        if not success and not error:
            error = message or f"Tool {tool_name} failed."
        return ToolResult(
            tool=tool_name,
            data=data,
            success=success,
            message=message,
            error=error if not success else None,
        )

    def _format_tool_failure(self, result: ToolResult) -> str:
        if result.error:
            return result.error
        if result.message:
            return result.message
        return f"Tool error ({result.tool})"

    # Shared validator instance for post-tool checks (non-strict).
    _workflow_validator = WorkflowValidator()

    def _post_tool_validate(self, result: ToolResult) -> ToolResult:
        """Validate current workflow state after a WORKFLOW_EDIT_TOOL succeeds.

        Uses ``strict=False`` because the workflow is still being built
        incrementally — we only check invariants that should never be
        violated: no self-loops, no duplicate IDs, valid node types,
        valid edge references, no cycles.

        Returns the original *result* if valid, or a new failed
        ``ToolResult`` if validation errors are found (triggers the
        orchestrator's existing retry mechanism).
        """
        nodes = self.workflow.get("nodes", [])
        if not nodes:
            # Nothing to validate yet
            return result

        # Build a minimal workflow dict for the validator
        workflow_dict = {
            "nodes": nodes,
            "edges": self.workflow.get("edges", []),
            "variables": self.workflow.get("variables", []),
        }
        is_valid, errors = self._workflow_validator.validate(workflow_dict, strict=False)
        if is_valid:
            return result

        error_text = "; ".join(f"[{e.code}] {e.message}" for e in errors)
        self._logger.warning(
            "Post-tool validation failed (%d errors): %s", len(errors), error_text,
        )
        return ToolResult(
            tool=result.tool,
            data={**result.data, "success": False, "error": error_text},
            success=False,
            message="",
            error=f"Workflow validation failed after tool execution: {error_text}",
        )

    def respond(
        self,
        user_message: str,
        *,
        has_files: Optional[List[Dict[str, Any]]] = None,
        stream: Optional[Callable[[str], None]] = None,
        allow_tools: bool = True,
        should_cancel: Optional[Callable[[], bool]] = None,
        on_tool_event: Optional[
            Callable[[str, str, Dict[str, Any], Optional[Dict[str, Any]]], None]
        ] = None,
        thinking_budget: Optional[int] = None,
        on_thinking: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Respond to a user message, optionally calling tools.

        Args:
            thinking_budget: Token budget for extended thinking (reasoning).
                When set, the LLM uses chain-of-thought before responding.
            on_thinking: Callback receiving thinking/reasoning text chunks
                as they stream from the LLM.
        """
        self._logger.info("Received message bytes=%d history_len=%d has_files=%s", len(user_message.encode("utf-8")), len(self.history), has_files)
        # Track which files are NEW this turn (for base64 injection into the message)
        # vs which files exist from previous turns (for tool access via session_state).
        new_files = has_files or []
        if new_files:
            self.uploaded_files = new_files
        self._logger.info("uploaded_files count=%d files=%s", len(self.uploaded_files), [f.get("name") for f in self.uploaded_files])

        def is_cancelled() -> bool:
            return bool(should_cancel and should_cancel())
        did_stream = False
        streamed_chunks: List[str] = []
        def finalize_cancel() -> str:
            partial = "".join(streamed_chunks)
            # Save all tool calls/results from this turn before cancellation.
            # messages[0] is system prompt, messages[1:len(self.history)+1] is
            # prior history — everything after that is this turn's work.
            turn_start = 1 + len(self.history)
            turn_messages = messages[turn_start:]
            if partial:
                turn_messages.append({"role": "assistant", "content": partial})
            elif not turn_messages:
                turn_messages.append({"role": "user", "content": user_message})

            # Fix dangling tool_use blocks: the API requires every tool_use to
            # have a matching tool_result. When we cancel mid-loop, the last
            # assistant message may have tool_use IDs without results.
            # Collect all tool_use IDs and all tool_result IDs, then fill gaps.
            tool_use_ids: set = set()
            tool_result_ids: set = set()
            for msg in turn_messages:
                if msg.get("role") == "assistant":
                    for tc in msg.get("tool_calls") or []:
                        tc_id = tc.get("id", "")
                        if tc_id:
                            tool_use_ids.add(tc_id)
                elif msg.get("role") == "tool":
                    tc_id = msg.get("tool_call_id", "")
                    if tc_id:
                        tool_result_ids.add(tc_id)
            missing = tool_use_ids - tool_result_ids
            if missing:
                # Insert cancelled tool results right after the last tool result
                # (or at the end if there are none)
                for tc_id in missing:
                    turn_messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": json.dumps({"cancelled": True, "error": "Tool call cancelled by user"}),
                    })

            # Tell the LLM its generation was interrupted so it can pick up
            # where it left off on the next turn
            turn_messages.append({
                "role": "user",
                "content": (
                    "[SYSTEM] Your previous response was interrupted by the user. "
                    "Any tool calls in progress may not have completed. "
                    "When the user sends their next message, continue from where you left off."
                ),
            })
            turn_messages.append({"role": "assistant", "content": "Understood."})
            self.history.extend(turn_messages)
            return partial
        tool_desc = generate_all_schemas(self.tools)

        system = build_system_prompt(
            has_files=self.uploaded_files,  # all files (current + previous) for prompt context
            allow_tools=allow_tools,
            current_workflow_id=self.current_workflow_id,
            current_workflow_name=self.current_workflow_name,
            guidance=self._guidance if self._guidance else None,
        )

        # Compact history if context window is filling up (>70% used).
        # Uses the actual input_tokens from the last API call when available,
        # otherwise falls back to a rough character-based estimate.
        self._compact_history_if_needed()

        # Build user message content — inject base64 images and PDFs if uploaded THIS TURN.
        # Only new_files get injected; previously uploaded files are already in history
        # and remain accessible to tools (view_image) via self.uploaded_files.
        _MAX_IMAGE_BYTES = 4_500_000
        _MAX_PDF_BYTES = 32_000_000
        effective_message: Any = user_message
        if new_files:
            content_blocks: List[Dict[str, Any]] = []
            for f in new_files:
                if f.get("file_type") == "image":
                    image_path = Path(f["path"])
                    if not image_path.exists():
                        self._logger.warning("Image file not found: %s", image_path)
                        continue
                    raw_bytes = image_path.read_bytes()
                    if len(raw_bytes) > _MAX_IMAGE_BYTES:
                        self._logger.warning(
                            "Image %s too large (%d bytes > %d), skipping",
                            image_path.name, len(raw_bytes), _MAX_IMAGE_BYTES,
                        )
                        continue
                    b64 = base64.b64encode(raw_bytes).decode()
                    suffix = image_path.suffix.lower()
                    media = "image/jpeg" if suffix in (".jpg", ".jpeg") else f"image/{suffix.lstrip('.')}"
                    self._logger.info(
                        "Injecting image %s (%d bytes, media=%s)", image_path.name, len(raw_bytes), media,
                    )
                    content_blocks.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": media, "data": b64},
                    })
                elif f.get("file_type") == "pdf":
                    pdf_path = Path(f["path"])
                    if not pdf_path.exists():
                        self._logger.warning("PDF file not found: %s", pdf_path)
                        continue
                    raw_bytes = pdf_path.read_bytes()
                    if len(raw_bytes) > _MAX_PDF_BYTES:
                        self._logger.warning(
                            "PDF %s too large (%d bytes > %d), skipping",
                            pdf_path.name, len(raw_bytes), _MAX_PDF_BYTES,
                        )
                        continue
                    b64 = base64.b64encode(raw_bytes).decode()
                    self._logger.info(
                        "Injecting PDF %s (%d bytes)", pdf_path.name, len(raw_bytes),
                    )
                    content_blocks.append({
                        "type": "document",
                        "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
                    })
            if content_blocks:
                # Append the text after the file(s) so the LLM sees both
                content_blocks.append({"type": "text", "text": user_message})
                effective_message = content_blocks

        messages = [
            {"role": "system", "content": system},
            *self.history,
            {"role": "user", "content": effective_message},
        ]
        try:
            def on_delta(delta: str) -> None:
                nonlocal did_stream
                if is_cancelled():
                    return
                did_stream = True
                streamed_chunks.append(delta)
                if stream:
                    stream(delta)

            if allow_tools:
                raw, tool_calls, usage = call_llm_with_tools(
                    messages,
                    tools=tool_desc,
                    tool_choice=None,
                    on_delta=on_delta if stream else None,
                    caller="orchestrator",
                    request_tag="initial",
                    should_cancel=should_cancel,
                    thinking_budget=thinking_budget,
                    on_thinking=on_thinking,
                )
            else:
                if stream:
                    raw = call_llm_stream(
                        messages,
                        on_delta=on_delta,
                        caller="orchestrator",
                        request_tag="initial_stream",
                        should_cancel=should_cancel,
                        thinking_budget=thinking_budget,
                        on_thinking=on_thinking,
                    )
                    raw = raw.strip()
                    tool_calls = []
                else:
                    raw, tool_calls, usage = call_llm_with_tools(
                        messages,
                        tools=None,
                        tool_choice="none",
                        caller="orchestrator",
                        request_tag="initial_no_tools",
                        should_cancel=should_cancel,
                        thinking_budget=thinking_budget,
                        on_thinking=on_thinking,
                    )
            # Store actual token usage from API response for context tracking.
            # call_llm_stream doesn't return usage, so only update when available.
            if 'usage' in dir() and isinstance(usage, dict):
                self._last_input_tokens = usage.get("input_tokens", 0)
            if is_cancelled():
                return finalize_cancel()
        except CancellationError:
            return finalize_cancel()
        except Exception as exc:
            self._logger.exception("LLM error while responding")
            error_msg = f"LLM error: {exc}"
            # Save to history before returning error
            self.history.append({"role": "user", "content": user_message})
            self.history.append({"role": "assistant", "content": error_msg})
            return error_msg

        tool_iterations = 0
        tool_results: List[ToolResult] = []
        asked_question = False
        while allow_tools and tool_calls:
            if is_cancelled():
                return finalize_cancel()
            tool_iterations += 1
            if tool_iterations > 50:
                self._logger.error(
                    "Max tool iterations reached. Tools called: %s",
                    [r.tool for r in tool_results]
                )
                error_msg = (
                    "Reached maximum tool iterations (50). "
                    f"Executed {len(tool_results)} tools successfully before stopping."
                )
                # Save to history before returning error
                self.history.append({"role": "user", "content": user_message})
                self.history.append({"role": "assistant", "content": error_msg})
                return error_msg

            self._logger.info("Tool iteration %d, calling %d tools", tool_iterations, len(tool_calls))

            messages.append(
                {
                    "role": "assistant",
                    "content": raw or "",
                    "tool_calls": tool_calls,
                }
            )

            tool_failure: Optional[ToolResult] = None
            asked_question = False
            skipped_calls: List[Dict[str, Any]] = []
            for idx, call in enumerate(tool_calls):
                if is_cancelled():
                    return finalize_cancel()
                fn = call.get("function") or {}
                tool_name = fn.get("name")
                args_text = fn.get("arguments") or "{}"
                if isinstance(args_text, str):
                    try:
                        args = json.loads(args_text)
                    except json.JSONDecodeError:
                        args = {}
                elif isinstance(args_text, dict):
                    args = args_text
                else:
                    args = {}
                try:
                    if on_tool_event:
                        on_tool_event("tool_start", tool_name, args, None)

                    # Build a progress callback that relays phase updates via on_tool_event
                    def _on_progress(status: str) -> None:
                        if on_tool_event:
                            on_tool_event("tool_progress", tool_name, {"status": status}, None)

                    # Forward LLM thinking chunks to the frontend via on_tool_event
                    def _on_thinking(chunk: str) -> None:
                        if on_tool_event:
                            on_tool_event("tool_thinking", tool_name, {"chunk": chunk}, None)

                    result = self.run_tool(
                        tool_name, args, stream=None, should_cancel=should_cancel,
                        on_progress=_on_progress, on_thinking=_on_thinking,
                    )
                    tool_results.append(result)
                    # If tool returned image blocks (list content), pass through directly
                    # so the LLM sees the image. Otherwise json.dumps the result dict.
                    tool_content = (
                        result.data.get("content")
                        if isinstance(result.data.get("content"), list)
                        else json.dumps(result.data)
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id"),
                            "content": tool_content,
                        }
                    )
                    if on_tool_event:
                        on_tool_event("tool_complete", tool_name, args, result.data)
                    # ask_question: stop the tool loop — wait for user's answer.
                    # The pending_question socket event was already emitted by
                    # on_tool_event, so the frontend shows the question card.
                    if tool_name == "ask_question" and result.success:
                        asked_question = True
                        break
                    if not result.success:
                        tool_failure = result
                        skipped_calls = tool_calls[idx + 1:]
                        break
                    if is_cancelled():
                        return finalize_cancel()
                except CancellationError:
                    return finalize_cancel()
                except Exception as exc:
                    self._tool_logger.error(
                        "tool_error name=%s error=%s",
                        tool_name,
                        str(exc),
                        exc_info=True,
                    )
                    error_msg = f"Tool error ({tool_name}): {exc}"
                    # Save to history before returning error
                    self.history.append({"role": "user", "content": user_message})
                    self.history.append({"role": "assistant", "content": error_msg})
                    return error_msg

            if tool_failure and skipped_calls:
                for skipped in skipped_calls:
                    fn = skipped.get("function") or {}
                    skipped_tool = fn.get("name")
                    skipped_args_text = fn.get("arguments") or "{}"
                    if isinstance(skipped_args_text, str):
                        try:
                            skipped_args = json.loads(skipped_args_text)
                        except json.JSONDecodeError:
                            skipped_args = {}
                    elif isinstance(skipped_args_text, dict):
                        skipped_args = skipped_args_text
                    else:
                        skipped_args = {}
                    skipped_payload = {
                        "success": False,
                        "skipped": True,
                        "error": (
                            f"Skipped {skipped_tool or 'tool'} because a previous tool failed."
                        ),
                    }
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": skipped.get("id"),
                            "content": json.dumps(skipped_payload),
                        }
                    )
                    if on_tool_event:
                        on_tool_event("tool_complete", skipped_tool, skipped_args, skipped_payload)

            if on_tool_event:
                on_tool_event("tool_batch_complete", "", {}, None)

            # ask_question was called — don't call LLM again, wait for user's answer
            if asked_question:
                break

            if is_cancelled():
                return finalize_cancel()

            # Trim messages if they've grown too large during the tool loop.
            # Keep the system prompt (first message) + most recent messages.
            _MAX_TOOL_MESSAGES = 200
            if len(messages) > _MAX_TOOL_MESSAGES:
                original_len = len(messages)
                messages = [messages[0]] + messages[-(_MAX_TOOL_MESSAGES - 1):]
                self._logger.warning(
                    "Tool loop messages trimmed from %d to %d to prevent context overflow",
                    original_len, len(messages),
                )

            raw, tool_calls, usage = call_llm_with_tools(
                messages,
                tools=tool_desc,
                tool_choice=None,
                on_delta=on_delta if stream else None,
                caller="orchestrator",
                request_tag="post_tool",
                should_cancel=should_cancel,
                thinking_budget=thinking_budget,
                on_thinking=on_thinking,
            )
            self._last_input_tokens = usage.get("input_tokens", 0)
            if is_cancelled():
                return finalize_cancel()

        # When ask_question broke the tool loop, don't dump tool result summaries
        # to the user — the pending_question event already handles the UX.
        if asked_question:
            final_text = raw or ""
        else:
            final_text = raw or (_summarize_tool_results(tool_results) if tool_results else "")

        # Ensure we never return empty response when tools were executed
        # (but not when ask_question paused the loop — empty is fine there)
        if tool_results and not final_text.strip() and not asked_question:
            final_text = f"Completed {len(tool_results)} tool operation(s)."
            self._logger.warning("Empty final response after %d tool calls - using fallback", len(tool_results))

        # Ensure we never return a completely empty response — the LLM sometimes
        # returns only a thinking block with no text and no tool calls, which
        # sends a blank chat_response to the frontend.
        if not final_text.strip():
            self._logger.warning(
                "LLM returned empty response with no tool calls (history=%d messages)",
                len(self.history),
            )
            final_text = (
                "I wasn't able to generate a response. "
                "Could you rephrase or provide more details?"
            )

        if stream and final_text and not did_stream:
            _emit_stream(stream, final_text)

        # Save the full turn to history: user message, all tool calls/results,
        # and the final assistant response. messages[0] is the system prompt,
        # messages[1:len(self.history)+1] is prior history — skip both.
        turn_start = 1 + len(self.history)
        turn_messages = messages[turn_start:]
        # Append the final assistant response (may not be in messages yet)
        if turn_messages and turn_messages[-1].get("role") != "assistant":
            turn_messages.append({"role": "assistant", "content": final_text})
        elif not turn_messages:
            turn_messages = [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": final_text},
            ]

        self.history.extend(turn_messages)
        self._logger.debug("History now has %d messages (%d from this turn)", len(self.history), len(turn_messages))
        return final_text



def _emit_stream(stream: Callable[[str], None], text: str, *, chunk_size: int = 800) -> None:
    if not text:
        return
    for idx in range(0, len(text), chunk_size):
        stream(text[idx : idx + chunk_size])


def _summarize_tool_results(results: List[ToolResult]) -> str:
    """Build a brief summary of tool results as fallback text."""
    parts: List[str] = []
    for result in results:
        if isinstance(result.data, dict) and result.data.get("skipped"):
            continue
        if not result.success:
            error_text = result.error or result.message or "Tool failed."
            parts.append(f"Tool failed ({result.tool}): {error_text}")
            continue
        if result.message:
            parts.append(result.message)
    return "\n\n".join(parts)
