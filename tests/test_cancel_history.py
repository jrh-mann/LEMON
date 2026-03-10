#!/usr/bin/env python
"""Test that cancellation preserves tool call history in orchestrator.

Simulates: send message → cancel during tool loop → send follow-up →
verify the agent remembers what tools it used before cancellation.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("LEMON_LOG_LEVEL", "WARNING")

from src.backend.agents.orchestrator_factory import build_orchestrator
from src.backend.storage.workflows import WorkflowStore


def main() -> None:
    # Build orchestrator
    orchestrator = build_orchestrator(PROJECT_ROOT)

    tmp_dir = tempfile.mkdtemp(prefix="lemon_cancel_test_")
    db_path = Path(tmp_dir) / "test.sqlite"
    workflow_store = WorkflowStore(db_path)
    workflow_id = "wf_cancel_test"
    user_id = "test_user"

    workflow_store.create_workflow(
        workflow_id=workflow_id, user_id=user_id,
        name="Cancel Test", description="",
        domain=None, tags=[], nodes=[], edges=[],
        inputs=[], outputs=[], tree={}, doubts=[],
        validation_score=0, validation_count=0,
        is_validated=False, output_type="string", is_draft=False,
    )

    orchestrator.workflow_store = workflow_store
    orchestrator.user_id = user_id
    orchestrator.current_workflow_id = workflow_id
    orchestrator.current_workflow_name = "Cancel Test"
    orchestrator.repo_root = PROJECT_ROOT

    # --- Turn 1: Send message, cancel after first few tool calls ---
    cancel_flag = threading.Event()
    tool_count = 0
    tools_seen: List[str] = []

    def on_tool_event(event: str, tool: str, args: Dict[str, Any], result: Optional[Dict[str, Any]]) -> None:
        nonlocal tool_count
        if event == "tool_start":
            tool_count += 1
            tools_seen.append(tool)
            print(f"  [{tool_count}] {tool}")
            # Cancel after 3 tool calls
            if tool_count >= 3:
                print(f"  >>> CANCELLING after {tool_count} tool calls")
                cancel_flag.set()

    print("=" * 60)
    print("TURN 1: Build workflow, cancel after 3 tool calls")
    print("=" * 60)

    response1 = orchestrator.respond(
        "Build a BMI calculator with height and weight inputs",
        allow_tools=True,
        should_cancel=cancel_flag.is_set,
        on_tool_event=on_tool_event,
    )

    print(f"\nTurn 1 response: {response1[:100]}...")
    print(f"History length after cancel: {len(orchestrator.history)}")

    # Check if history contains tool_calls
    has_tool_calls = any(
        m.get("tool_calls") for m in orchestrator.history
    )
    print(f"History has tool_calls: {has_tool_calls}")

    # Print history roles for debugging
    print("\nHistory messages:")
    for i, m in enumerate(orchestrator.history):
        role = m.get("role", "?")
        has_tc = bool(m.get("tool_calls"))
        content_preview = str(m.get("content", ""))[:80]
        print(f"  [{i}] role={role} tool_calls={has_tc} content={content_preview}")

    # --- Turn 2: Ask what it did ---
    print("\n" + "=" * 60)
    print("TURN 2: Ask what it remembers")
    print("=" * 60)

    response2 = orchestrator.respond(
        "What tools did you just use? List the tool names.",
        allow_tools=False,
    )

    print(f"\nTurn 2 response:\n{response2}")

    # --- Validate ---
    print("\n" + "=" * 60)
    print("RESULT")
    print("=" * 60)

    # Check if the response mentions any of the tools we saw
    mentions_tools = any(tool in response2.lower() for tool in [
        "add_workflow_variable", "update_plan", "add_node", "batch_edit",
    ])
    no_memory_phrase = "don't have memory" in response2.lower() or "no memory" in response2.lower() or "starts fresh" in response2.lower()

    if mentions_tools and not no_memory_phrase:
        print("PASS — Agent remembers tool calls after cancellation")
    else:
        print("FAIL — Agent lost tool call history after cancellation")
        if no_memory_phrase:
            print("  Agent said it has no memory of previous conversations")

    sys.exit(0 if (mentions_tools and not no_memory_phrase) else 1)


if __name__ == "__main__":
    main()
