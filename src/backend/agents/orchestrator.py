"""Orchestrator for tool-based CLI use."""

from __future__ import annotations

from dataclasses import dataclass
import os
import json
import logging
from typing import Any, Callable, Dict, List, Optional

from ..tools import ToolRegistry
from ..tools.constants import WORKFLOW_EDIT_TOOLS, WORKFLOW_INPUT_TOOLS
from ..mcp.client import call_mcp_tool
from ..llm import call_llm_stream, call_llm_with_tools
from .orchestrator_config import build_system_prompt, tool_descriptions
from ..utils.cancellation import CancellationError


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
        self.last_session_id: Optional[str] = None

        # Single canonical workflow dict (nodes + edges + inputs + outputs + metadata)
        self.workflow: Dict[str, Any] = {
            "nodes": [],
            "edges": [],
            "inputs": [],
            "outputs": [],
            "tree": {},
            "doubts": []
        }

        self.history: List[Dict[str, str]] = []
        self._logger = logging.getLogger(__name__)
        self._tool_logger = logging.getLogger("backend.tool_calls")
        self._use_mcp = os.environ.get("LEMON_USE_MCP", "").lower() not in {"0", "false", "no"}

        # Session context for tools (workflow_store, user_id)
        self.workflow_store: Optional[Any] = None
        self.user_id: Optional[str] = None

    # Backward-compatible properties for existing code
    @property
    def current_workflow(self) -> Dict[str, Any]:
        """View of workflow structure (nodes/edges only) for backward compatibility."""
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
        """View of workflow metadata (inputs/outputs/tree/doubts) for backward compatibility."""
        return {
            "inputs": self.workflow.get("inputs", []),
            "outputs": self.workflow.get("outputs", []),
            "tree": self.workflow.get("tree", {}),
            "doubts": self.workflow.get("doubts", [])
        }

    @workflow_analysis.setter
    def workflow_analysis(self, value: Dict[str, Any]) -> None:
        if not isinstance(value, dict):
            return
        inputs = value.get("inputs", [])
        outputs = value.get("outputs", [])
        if isinstance(inputs, list):
            self.workflow["inputs"] = inputs
        if isinstance(outputs, list):
            self.workflow["outputs"] = outputs
        if "tree" in value and isinstance(value.get("tree"), dict):
            self.workflow["tree"] = value.get("tree", {})
        if "doubts" in value and isinstance(value.get("doubts"), list):
            self.workflow["doubts"] = value.get("doubts", [])

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

    def sync_workflow_analysis(
        self,
        analysis_provider: Optional[Callable[[], Dict[str, Any]]] = None
    ) -> None:
        """Sync workflow metadata (inputs/outputs/tree/doubts) from external source.

        Args:
            analysis_provider: Callable that returns workflow analysis (inputs/outputs).
                              None = use existing memory state (no-op).

        Design: Uses dependency injection to decouple from storage.
                Caller controls WHERE state comes from.
        """
        if analysis_provider is None:
            return  # No sync needed

        try:
            analysis_data = analysis_provider()
        except Exception as exc:
            self._logger.error("Failed to sync workflow analysis: %s", exc)
            return

        if not isinstance(analysis_data, dict):
            return

        inputs = analysis_data.get("inputs", [])
        outputs = analysis_data.get("outputs", [])

        if isinstance(inputs, list) and isinstance(outputs, list):
            # Update the unified workflow dict
            self.workflow["inputs"] = inputs
            self.workflow["outputs"] = outputs
            if "tree" in analysis_data:
                self.workflow["tree"] = analysis_data.get("tree", {})
            if "doubts" in analysis_data:
                self.workflow["doubts"] = analysis_data.get("doubts", [])
            self._logger.info(
                "Synced workflow analysis: %d inputs, %d outputs",
                len(inputs),
                len(outputs)
            )

    def run_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        *,
        stream: Optional[Callable[[str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> ToolResult:
        self._logger.info("Running tool name=%s args_keys=%s", tool_name, sorted(args.keys()))
        self._tool_logger.info(
            "tool_request name=%s args=%s",
            tool_name,
            json.dumps(args, ensure_ascii=True),
        )

        # Build session_state with workflow context and user context
        session_state = {
            "current_workflow": self.current_workflow,
            "workflow_analysis": self.workflow_analysis,
        }
        # Add workflow_store and user_id if available
        if self.workflow_store is not None:
            session_state["workflow_store"] = self.workflow_store
        if self.user_id is not None:
            session_state["user_id"] = self.user_id

        if self._use_mcp:
            # Pass session_state through MCP as a regular argument
            mcp_args = {
                **args,
                "session_state": session_state,
            }
            data = call_mcp_tool(tool_name, mcp_args)
        else:
            data = self.tools.execute(
                tool_name,
                args,
                stream=stream,
                should_cancel=should_cancel,
                session_state=session_state,
            )
        result = self._normalize_tool_result(tool_name, data)
        self._tool_logger.info(
            "tool_response name=%s data=%s",
            tool_name,
            json.dumps(result.data, ensure_ascii=True),
        )

        # Update current_workflow if this was a successful workflow manipulation tool
        if result.success:
            if tool_name in WORKFLOW_EDIT_TOOLS:
                self._update_workflow_from_tool_result(tool_name, result.data)

            # Update workflow_analysis if this was a successful input management tool
            if tool_name in WORKFLOW_INPUT_TOOLS:
                self._update_analysis_from_tool_result(tool_name, result.data)

        # Also update workflow when publish_latest_analysis returns a flowchart
        if tool_name == "publish_latest_analysis" and isinstance(result.data, dict):
            flowchart = (
                result.data.get("flowchart")
                if isinstance(result.data.get("flowchart"), dict)
                else None
            )
            if flowchart and flowchart.get("nodes"):
                self.workflow["nodes"] = flowchart.get("nodes", [])
                self.workflow["edges"] = flowchart.get("edges", [])

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

    def _update_workflow_from_tool_result(self, tool_name: str, result: Dict[str, Any]) -> None:
        """Update workflow structure based on successful tool execution."""
        if tool_name == "add_node":
            node = result.get("node")
            if node:
                self.workflow["nodes"].append(node)

        elif tool_name == "modify_node":
            node = result.get("node")
            if node:
                nodes = self.workflow["nodes"]
                for i, n in enumerate(nodes):
                    if n["id"] == node["id"]:
                        nodes[i] = node
                        break

        elif tool_name == "delete_node":
            node_id = result.get("node_id")
            if node_id:
                self.workflow["nodes"] = [
                    n for n in self.workflow["nodes"] if n["id"] != node_id
                ]
                self.workflow["edges"] = [
                    e for e in self.workflow["edges"]
                    if e["from"] != node_id and e["to"] != node_id
                ]

        elif tool_name == "add_connection":
            edge = result.get("edge")
            if edge:
                self.workflow["edges"].append(edge)

        elif tool_name == "delete_connection":
            from_id = result.get("from_node_id")
            to_id = result.get("to_node_id")
            if from_id and to_id:
                self.workflow["edges"] = [
                    e for e in self.workflow["edges"]
                    if not (e["from"] == from_id and e["to"] == to_id)
                ]

        elif tool_name == "batch_edit_workflow":
            new_workflow = result.get("workflow")
            if new_workflow:
                self.workflow["nodes"] = new_workflow.get("nodes", [])
                self.workflow["edges"] = new_workflow.get("edges", [])

    def _update_analysis_from_tool_result(self, tool_name: str, result: Dict[str, Any]) -> None:
        """Update workflow metadata based on successful input tool execution.

        For direct tool calls: Tools modify session_state["workflow_analysis"] directly (by reference).
        For MCP calls: Tools return workflow_analysis in response, we must sync it back.
        """
        if tool_name in WORKFLOW_INPUT_TOOLS:
            # MCP mode: Extract workflow_analysis from response and sync
            if "workflow_analysis" in result:
                returned_analysis = result["workflow_analysis"]
                if isinstance(returned_analysis, dict):
                    # Update inputs and outputs in the unified workflow dict
                    if "inputs" in returned_analysis:
                        self.workflow["inputs"] = returned_analysis["inputs"]
                    if "outputs" in returned_analysis:
                        self.workflow["outputs"] = returned_analysis["outputs"]
                    self._logger.debug(
                        "Synced workflow_analysis from tool result: %d inputs, %d outputs",
                        len(self.workflow.get("inputs", [])),
                        len(self.workflow.get("outputs", [])),
                    )

            # CRITICAL: Also sync current_workflow if tool modified nodes/edges
            # (e.g., remove_workflow_input with force=true removes input_ref from nodes)
            if "current_workflow" in result:
                returned_workflow = result["current_workflow"]
                if isinstance(returned_workflow, dict):
                    if "nodes" in returned_workflow:
                        self.workflow["nodes"] = returned_workflow["nodes"]
                    if "edges" in returned_workflow:
                        self.workflow["edges"] = returned_workflow["edges"]
                    self._logger.debug(
                        "Synced current_workflow from tool result: %d nodes, %d edges",
                        len(self.workflow.get("nodes", [])),
                        len(self.workflow.get("edges", [])),
                    )

    def respond(
        self,
        user_message: str,
        *,
        has_image: bool = False,
        stream: Optional[Callable[[str], None]] = None,
        allow_tools: bool = True,
        should_cancel: Optional[Callable[[], bool]] = None,
        on_tool_event: Optional[
            Callable[[str, str, Dict[str, Any], Optional[Dict[str, Any]]], None]
        ] = None,
    ) -> str:
        """Respond to a user message, optionally calling tools."""
        self._logger.info("Received message bytes=%d history_len=%d", len(user_message.encode("utf-8")), len(self.history))
        def is_cancelled() -> bool:
            return bool(should_cancel and should_cancel())
        did_stream = False
        streamed_chunks: List[str] = []
        def finalize_cancel() -> str:
            partial = "".join(streamed_chunks)
            self.history.append({"role": "user", "content": user_message})
            if partial:
                self.history.append({"role": "assistant", "content": partial})
            return partial
        tool_desc = tool_descriptions()
        system = build_system_prompt(
            last_session_id=self.last_session_id,
            has_image=has_image,
            allow_tools=allow_tools,
        )

        # Limit history to last 20 messages (10 exchanges) to prevent context overflow
        limited_history = self.history[-20:] if len(self.history) > 20 else self.history
        if len(self.history) > 20:
            self._logger.warning(
                "History truncated from %d to 20 messages to fit context window",
                len(self.history)
            )

        messages = [
            {"role": "system", "content": system},
            *limited_history,
            {"role": "user", "content": user_message},
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
                raw, tool_calls = call_llm_with_tools(
                    messages,
                    tools=tool_desc,
                    tool_choice=None,
                    on_delta=on_delta if stream else None,
                    caller="orchestrator",
                    request_tag="initial",
                    should_cancel=should_cancel,
                )
            else:
                if stream:
                    raw = call_llm_stream(
                        messages,
                        on_delta=on_delta,
                        caller="orchestrator",
                        request_tag="initial_stream",
                        should_cancel=should_cancel,
                    )
                    raw = raw.strip()
                    tool_calls = []
                else:
                    raw, tool_calls = call_llm_with_tools(
                        messages,
                        tools=None,
                        tool_choice="none",
                        caller="orchestrator",
                        request_tag="initial_no_tools",
                        should_cancel=should_cancel,
                    )
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
                    result = self.run_tool(tool_name, args, stream=None, should_cancel=should_cancel)
                    session_id = result.data.get("session_id")
                    if session_id:
                        self.last_session_id = session_id
                    tool_results.append(result)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id"),
                            "content": json.dumps(result.data),
                        }
                    )
                    if on_tool_event:
                        on_tool_event("tool_complete", tool_name, args, result.data)
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

            if is_cancelled():
                return finalize_cancel()

            messages.append(
                {
                    "role": "system",
                    "content": (
                        "A tool call failed. The tool result and error details are provided above. "
                        "Explain the failure clearly to the user and suggest next steps. "
                        "If you can recover with additional tool calls, you may call them. "
                        "Otherwise respond in plain text."
                        if tool_failure
                        else "Tool execution succeeded. The tool results are provided above. "
                        "If additional tool calls are required to complete the user's request, "
                        "you may call them (including multiple tool calls). Otherwise respond in "
                        "plain text only, summarizing "
                        "inputs, outputs, and doubts."
                    ),
                }
            )
            raw, tool_calls = call_llm_with_tools(
                messages,
                tools=tool_desc,
                tool_choice=None,
                on_delta=on_delta if stream else None,
                caller="orchestrator",
                request_tag="post_tool",
                should_cancel=should_cancel,
            )
            if is_cancelled():
                return finalize_cancel()

        final_text = raw or (_summarize_tool_results(tool_results) if tool_results else "")

        # Ensure we never return empty response when tools were executed
        if tool_results and not final_text.strip():
            final_text = f"Completed {len(tool_results)} tool operation(s)."
            self._logger.warning("Empty final response after %d tool calls - using fallback", len(tool_results))

        if stream and final_text and not did_stream:
            _emit_stream(stream, final_text)

        self.history.append({"role": "user", "content": user_message})
        self.history.append({"role": "assistant", "content": final_text})
        self._logger.debug("History now has %d messages", len(self.history))
        return final_text



def _emit_stream(stream: Callable[[str], None], text: str, *, chunk_size: int = 800) -> None:
    if not text:
        return
    for idx in range(0, len(text), chunk_size):
        stream(text[idx : idx + chunk_size])


def _summarize_tool_results(results: List[ToolResult]) -> str:
    parts: List[str] = []
    for result in results:
        if isinstance(result.data, dict) and result.data.get("skipped"):
            continue
        if not result.success:
            error_text = result.error or result.message or "Tool failed."
            header = f"Tool failed ({result.tool})."
            parts.append(f"{header}\n\n{error_text}".strip())
            continue
        if result.message:
            message = result.message
            header = f"Discussion ({result.tool})." if len(results) > 1 else "Discussion."
            parts.append(f"{header}\n\n{message}".strip())
            continue
        analysis = result.data.get("analysis") if isinstance(result.data, dict) else {}
        if not isinstance(analysis, dict):
            analysis = {}
        inputs = analysis.get("inputs") if isinstance(analysis.get("inputs"), list) else []
        outputs = analysis.get("outputs") if isinstance(analysis.get("outputs"), list) else []
        doubts = analysis.get("doubts") if isinstance(analysis.get("doubts"), list) else []

        def _fmt_items(items: list, key: str) -> str:
            lines = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or item.get(key) or ""
                typ = item.get("type")
                if typ:
                    lines.append(f"- {name} ({typ})")
                else:
                    lines.append(f"- {name}")
            return "\n".join(lines) if lines else "- None"

        inputs_text = _fmt_items(inputs, "input")
        outputs_text = _fmt_items(outputs, "output")
        doubts_text = "\n".join(f"- {d}" for d in doubts) if doubts else "- None"
        header = f"Analysis complete ({result.tool})." if len(results) > 1 else "Analysis complete."
        parts.append(
            f"{header}\n\n"
            "Inputs:\n"
            f"{inputs_text}\n\n"
            "Outputs:\n"
            f"{outputs_text}\n\n"
            "Doubts:\n"
            f"{doubts_text}"
        )
    return "\n\n".join(parts)
