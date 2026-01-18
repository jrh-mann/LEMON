"""
Agentic chatbot loop: Claude executes tasks autonomously with continuation support.
"""

import asyncio
import json
import base64
import tempfile
from pathlib import Path
import re
import sys
from typing import Any, Dict, List

from .config import Settings
from .llm_client import ClaudeClient
from .mcp_client import McpClient
from .tool_bridge import ToolBridge
from .logging import get_logger


# Patterns that suggest the task is incomplete
INCOMPLETE_PATTERNS = [
    r"(?i)\b(next|then|now|after that|continuing|proceeding)\b",
    r"(?i)\b(will|going to|about to|need to|should)\b.*\b(click|type|open|close|find|wait)\b",
    r"(?i)\b(step \d+|first|second|third|finally)\b",
    r"(?i)\b(let me|i('ll| will))\b.*\b(continue|proceed|finish)\b",
    r"(?i)\b(remaining|left to do|more steps)\b",
]

# Patterns that suggest task is complete
COMPLETE_PATTERNS = [
    r"(?i)\b(completed?|done|finished|accomplished|successfully)\b",
    r"(?i)\b(task (is )?complete|all (steps )?done)\b",
    r"(?i)\b(that('s| is) (all|everything)|nothing (more|else))\b",
    r"(?i)\b(summary|in summary|to summarize)\b.*\b(completed?|done|accomplished)\b",
]

# Patterns that indicate an error/failure requiring user input
FAILURE_PATTERNS = [
    r"(?i)\b(cannot|can't|couldn't|unable to|failed to)\b.*\b(complete|finish|proceed)\b",
    r"(?i)\b(error|failure|problem|issue)\b.*\b(prevent|block|stop)\b",
    r"(?i)\b(need (your )?help|require (your )?input|please (provide|specify))\b",
]

ACTION_TOOLS = {
    "click_element",
    "type_text",
    "send_keys",
    "send_hotkey",
    "batch_actions",
    "click_at",
    "move_mouse",
    "drag_and_drop",
    "scroll_at",
    "focus_window",
}

VERIFICATION_TOOLS = {
    "get_focused_element",
    "find_element",
    "get_clickable_elements",
    "get_elements_in_region",
    "get_child_elements",
    "wait_for_element",
    "screenshot_window",
    "read_clipboard",
    "get_element_tree",
}


class Chatbot:
    """
    Agentic chatbot that executes tasks autonomously with continuation support.
    Uses extended thinking for complex multi-step reasoning.
    """

    # Agent configuration
    MAX_ITERATIONS = 1000  # Safety limit for agent loop
    MAX_CONTINUATIONS = 5  # Max times to auto-continue after text-only response
    CONTINUATION_PROMPT = "Continue executing the remaining steps. Do not explain, just act."

    def __init__(self):
        self.settings = Settings.load()
        self.logger = get_logger("chatbot")
        self.mcp = McpClient()
        self.tool_bridge = ToolBridge(self.mcp)
        self.messages: List[Dict[str, Any]] = []
        self.llm = ClaudeClient(
            client=self.settings.anthropic_client(),
            model=self.settings.model,
            system_prompt=self.settings.system_prompt,
            max_tokens=self.settings.max_tokens,
            thinking_budget=self.settings.thinking_budget,
            enable_thinking=True,
        )
        self.response_timeout_seconds = 120  # Increased for extended thinking
        # Toggle for agentic auto-continuation; set False to disable harness-style auto-driving.
        self.agentic = False
        
        # Agent state tracking
        self._iteration_count = 0
        self._continuation_count = 0
        self._tool_calls_this_turn = 0
        self._streamed_output_shown = False
        self._pending_verification = False
        self._no_progress_count = 0

    async def start(self) -> None:
        await self.mcp.connect()
        await self.tool_bridge.refresh_tools()
        tool_names = [t["name"] for t in self.tool_bridge.anthropic_tools]
        self.logger.info("Ready with tools: %s", tool_names)
        print(f"\n🤖 Windows UI Automation Agent (Claude)")
        print(f"   Tools: {len(tool_names)} available")
        print(f"   Max iterations: {self.MAX_ITERATIONS}")
        print(f"   Extended thinking: enabled")
        print(f"\nType 'exit' to quit.\n")

    async def stop(self) -> None:
        await self.mcp.disconnect()

    def _reset_turn_state(self) -> None:
        """Reset per-turn tracking state."""
        self._iteration_count = 0
        self._continuation_count = 0
        self._tool_calls_this_turn = 0
        self._streamed_output_shown = False
        self._pending_verification = False
        self._no_progress_count = 0

    def _is_task_complete(self, text: str) -> bool:
        """
        Analyze response text to determine if the task appears complete.
        """
        if not text:
            return False
        
        # Check for explicit completion patterns
        for pattern in COMPLETE_PATTERNS:
            if re.search(pattern, text):
                return True
        
        return False

    def _is_task_incomplete(self, text: str) -> bool:
        """
        Analyze response text to determine if the task appears incomplete.
        """
        if not text:
            return False
        
        # Check for failure patterns first (these should not trigger continuation)
        for pattern in FAILURE_PATTERNS:
            if re.search(pattern, text):
                return False
        
        # Check for incomplete patterns
        for pattern in INCOMPLETE_PATTERNS:
            if re.search(pattern, text):
                return True
        
        return False

    def _should_continue(self, text: str, had_tool_use: bool) -> bool:
        """
        Determine if we should auto-continue after a text-only response.
        """
        # If there were tool uses, we already continued in the loop
        if had_tool_use:
            return False
        
        # Don't exceed continuation limit
        if self._continuation_count >= self.MAX_CONTINUATIONS:
            self.logger.info("Hit max continuations (%d), stopping", self.MAX_CONTINUATIONS)
            return False
        
        # If task seems complete, don't continue
        if self._is_task_complete(text):
            return False
        
        # If task seems incomplete, continue
        if self._is_task_incomplete(text):
            return True
        
        # If we've had tool calls this turn but got a text response,
        # the model might be pausing unnecessarily
        if self._tool_calls_this_turn > 0:
            return True
        
        return False

    async def _run_tools(self, tool_uses: List[Any], live: bool = False) -> List[Dict[str, Any]]:
        handlers = self.tool_bridge.function_map()
        results: List[Dict[str, Any]] = []

        for use in tool_uses:
            name = getattr(use, "name", "")
            args = getattr(use, "input", {}) or {}
            tool_id = getattr(use, "id", "")

            fn = handlers.get(name)
            if live:
                print(f"Assistant: [tool] {name} {args}", flush=True)
            if not fn:
                err = {"error": f"Unknown tool: {name}"}
                results.append({"type": "tool_result", "tool_use_id": tool_id, "content": json.dumps(err)})
                continue

            try:
                resp = await fn(**args)
                resp = self._strip_image_payload(resp)
                if live:
                    summary = self._summarize_tool_result(name, resp)
                    print(f"Assistant: [tool result] {name} -> {summary}", flush=True)
                results.append({"type": "tool_result", "tool_use_id": tool_id, "content": self._compact_tool_result(resp)})
            except Exception as exc:  # pylint: disable=broad-except
                if live:
                    print(f"Assistant: [tool error] {name}: {exc}", flush=True)
                err = {"error": str(exc)}
                results.append({"type": "tool_result", "tool_use_id": tool_id, "content": self._compact_tool_result(err)})

        return results

    async def _next_assistant_turn(self, live: bool = False) -> Any:
        """
        Get the next assistant response, with optional streaming and thinking display.
        """
        self._iteration_count += 1
        # Reset streamed output flag for this assistant turn
        self._streamed_output_shown = False
        
        if self._iteration_count > self.MAX_ITERATIONS:
            raise RuntimeError(f"Agent exceeded max iterations ({self.MAX_ITERATIONS})")
        
        if not live:
            return await self.llm.complete(self.messages, self.tool_bridge.anthropic_tools)

        streamed_chunks: List[str] = []
        thinking_shown = False

        def on_text(text: str):
            streamed_chunks.append(text)
            print(text, end="", flush=True)

        def on_thinking(thinking: str):
            nonlocal thinking_shown
            if not thinking_shown:
                print("💭 ", end="", flush=True)
                thinking_shown = True
            # Show abbreviated thinking (first 100 chars of each chunk)
            if len(thinking) > 100:
                print(".", end="\n", flush=True)
            else:
                print(thinking[:50], end="", flush=True)

        msg = await self.llm.stream(
            self.messages, 
            self.tool_bridge.anthropic_tools, 
            on_text=on_text,
            on_thinking=on_thinking
        )
        
        if thinking_shown:
            print()  # Newline after thinking
        if streamed_chunks:
            print()
            self._streamed_output_shown = True
        return msg

    def _assistant_text(self, content_blocks: List[Any]) -> str:
        return "".join(getattr(b, "text", "") for b in content_blocks if getattr(b, "type", "") == "text").strip()

    def _strip_image_payload(self, resp: Any) -> Any:
        """
        If the tool result contains an imageBase64 payload, persist it to a temp file,
        add metadata (imagePath/contentType/isImage/sizeBytes), and remove the base64
        to keep prompts small.
        """
        if not isinstance(resp, dict):
            return resp
        data = resp.get("data")
        if not isinstance(data, dict):
            return resp
        b64 = data.pop("imageBase64", None)
        if not b64:
            return resp
        try:
            img_bytes = base64.b64decode(b64)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png", prefix="screenshot_")
            tmp.write(img_bytes)
            tmp.close()
            data["imagePath"] = str(Path(tmp.name))
            data["contentType"] = data.get("contentType", "image/png")
            data["isImage"] = True
            data["sizeBytes"] = len(img_bytes)
        except Exception as exc:  # pylint: disable=broad-except
            warnings = data.get("warnings") or []
            if isinstance(warnings, list):
                warnings.append(f"Failed to persist image: {exc}")
                data["warnings"] = warnings
            data["isImage"] = True
            data["contentType"] = "image/png"
        # Remove the huge raw blob if present; replace with a short note.
        if "raw" in resp:
            resp["raw"] = "[image payload omitted]"
        return resp

    def _summarize_tool_result(self, name: str, resp: Any) -> str:
        """
        Build a short, readable summary for console output.
        """
        payload = resp
        if isinstance(resp, dict) and "data" in resp and resp.get("data") not in (None, {}):
            payload = resp["data"]

        if not isinstance(payload, dict):
            txt = str(payload)
            return txt if len(txt) <= 160 else txt[:157] + "..."

        success = payload.get("success")
        message = payload.get("message")

        # Image tool summary
        if isinstance(payload, dict):
            data = payload.get("data") if "data" in payload else payload
            if isinstance(data, dict) and data.get("isImage"):
                path = data.get("imagePath")
                bounds = data.get("bounds")
                return f"image success={success} path={path} bounds={bounds}"

        if name == "launch_app":
            proc = payload.get("processName") or payload.get("processId")
            count = payload.get("newWindowCount")
            return f"success={success} process={proc} new_windows={count}"

        if name == "list_windows":
            wins = payload.get("windows") or []
            titles = [w.get("title") for w in wins if w.get("title")]
            return f"success={success} windows={len(wins)} [{', '.join(titles[:3])}]"

        if name == "get_session_state":
            state = payload.get("sessionState") or {}
            return f"success={success} windows={state.get('windowCount')} elements={state.get('elementCount')}"

        if message:
            return f"success={success} message={message}"

        txt = json.dumps(payload)
        return txt if len(txt) <= 160 else txt[:157] + "..."

    def _compact_tool_result(self, resp: Any, max_len: int = 4000) -> str:
        try:
            text = json.dumps(resp)
        except Exception:
            text = str(resp)
        if len(text) > max_len:
            text = text[:max_len] + f"... [truncated {len(text) - max_len} chars]"
        return text

    def _maybe_print_text(self, blocks: List[Any], live: bool) -> None:
        if not live:
            return
        if self._streamed_output_shown:
            return
        text = self._assistant_text(blocks)
        if text:
            print(f"Assistant: {text}", flush=True)

    async def handle_user_message(self, text: str, live: bool = False) -> str:
        """
        Process a user message with full agent loop support.
        
        Features:
        - Continues executing tools until task complete
        - Auto-continues if Claude pauses mid-task with text
        - Safety limits on iterations and continuations
        - Extended thinking for complex reasoning
        """
        self._reset_turn_state()
        self.messages.append({"role": "user", "content": text})

        while True:
            try:
                response = await asyncio.wait_for(
                    self._next_assistant_turn(live=live),
                    timeout=self.response_timeout_seconds,
                )
            except asyncio.TimeoutError:
                msg = f"⏱️ Timed out after {self.response_timeout_seconds}s. Task may be incomplete."
                self.logger.warning(msg)
                return msg
            except RuntimeError as e:
                # Max iterations exceeded
                self.logger.error(str(e))
                return f"⚠️ {e}"

            blocks = response.content or []
            tool_uses = [b for b in blocks if getattr(b, "type", "") == "tool_use"]
            response_text = self._assistant_text(blocks)

            self.messages.append({"role": "assistant", "content": blocks})

            if tool_uses:
                # Track tool usage
                self._tool_calls_this_turn += len(tool_uses)
                tool_names = {getattr(t, "name", "") for t in tool_uses}
                action_seen = any(n in ACTION_TOOLS for n in tool_names)
                verification_seen = any(n in VERIFICATION_TOOLS for n in tool_names)
                
                # Execute tools
                tool_results = await self._run_tools(tool_uses, live=live)
                self.messages.append({"role": "user", "content": tool_results})

                if action_seen and not verification_seen:
                    self._pending_verification = True
                if verification_seen:
                    self._pending_verification = False
                    self._no_progress_count = 0
                # Continue loop to get next response
                continue

            # No tool uses - Claude responded with text only
            self._maybe_print_text(blocks, live)

            # If actions occurred without verification, force a verification/replan prompt
            if self._pending_verification:
                self._no_progress_count += 1
                prompt = (
                    "VERIFY LAST ACTIONS BEFORE PROCEEDING: "
                    "Do not continue the task until you re-scan and confirm focus/value or visible change. "
                    "Use a verification tool (get_focused_element, find_element with filters, get_clickable_elements typeable_only, "
                    "get_elements_in_region, get_child_elements, wait_for_element, read_clipboard after copy, or screenshot_window) to confirm progress."
                )
                if self._no_progress_count >= 2:
                    prompt = (
                        "REPLAN: multiple actions without verified progress. "
                        "Re-scan (list_windows + discovery), verify focus, and adjust strategy before acting again."
                    )
                if live:
                    print(f"⚠️ {prompt}", flush=True)
                self.messages.append({"role": "user", "content": prompt})
                # Keep looping to force verification/replan
                continue

            # Check if we should auto-continue
            if self.agentic and self._should_continue(response_text, had_tool_use=False):
                self._continuation_count += 1
                if live:
                    print(f"🔄 Auto-continuing ({self._continuation_count}/{self.MAX_CONTINUATIONS})...", flush=True)
                self.logger.info("Auto-continuing: iteration=%d, continuations=%d", 
                               self._iteration_count, self._continuation_count)
                self.messages.append({"role": "user", "content": self.CONTINUATION_PROMPT})
                continue

            # Task appears complete or we hit limits
            if live and self._tool_calls_this_turn > 0:
                print(f"✅ Completed: {self._tool_calls_this_turn} tool calls in {self._iteration_count} iterations", flush=True)
            
            return response_text

    async def run_console(self) -> None:
        """
        Main console loop for the agent.
        """
        await self.start()
        try:
            while True:
                try:
                    user_input = input("You: ").strip()
                except EOFError:
                    break
                    
                if not user_input:
                    continue
                if user_input.lower() in {"exit", "quit", "bye"}:
                    print("👋 Goodbye!")
                    break
                
                # Handle special commands
                if user_input.lower() == "status":
                    print(f"📊 Messages in history: {len(self.messages)}")
                    print(f"   Tools available: {len(self.tool_bridge.anthropic_tools)}")
                    continue
                if user_input.lower() == "clear":
                    self.messages.clear()
                    print("🗑️ Conversation history cleared.")
                    continue
                if user_input.lower() == "help":
                    self._print_help()
                    continue
                
                try:
                    await self.handle_user_message(user_input, live=True)
                except Exception as exc:  # pylint: disable=broad-except
                    self.logger.exception("Agent turn failed")
                    print(f"❌ Error: {exc}")
                print()
        finally:
            await self.stop()

    def _print_help(self) -> None:
        """Print help information."""
        print("""
🤖 Agent Commands:
  exit/quit/bye  - Exit the agent
  status         - Show conversation stats
  clear          - Clear conversation history
  help           - Show this help

💡 Tips:
  - Give complete task descriptions for best results
  - The agent will auto-continue if it pauses mid-task
  - Use 'clear' to reset if the agent gets confused
  - Complex tasks may take multiple iterations
        """)


async def main():
    """Entry point for the Windows UI Automation Agent."""
    chatbot = Chatbot()
    if any(arg in ("--agentic", "--auto") for arg in sys.argv[1:]):
        chatbot.agentic = True
        print("Agentic mode enabled via CLI flag (--agentic).")
    await chatbot.run_console()
