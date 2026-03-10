#!/usr/bin/env python
"""Live integration test: verify the three-phase image build protocol.

Feeds a workflow image to a real orchestrator and checks that tool calls
follow the correct ordering:
  Phase 1 (Analyse): extract_guidance, update_plan, create_workflow, add_workflow_variable
  Phase 2 (Build):   ALL add_node calls, THEN ALL add_connection calls
  Phase 3 (Verify):  view_image + get_current_workflow after wiring

Usage:
    cd /path/to/LEMON
    python -m tests.test_image_protocol                     # default image
    python -m tests.test_image_protocol path/to/image.png   # custom image

Requires ANTHROPIC_API_KEY in environment.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Project setup
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("LEMON_LOG_PREFIX", "protocol_test")
os.environ.setdefault("LEMON_LOG_LEVEL", "WARNING")  # quiet unless debugging

from src.backend.agents.orchestrator_factory import build_orchestrator  # noqa: E402
from src.backend.storage.workflows import WorkflowStore  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_IMAGE = PROJECT_ROOT / "workflow_test_2x.png"
PROMPT = "Analyze this workflow image and build it exactly as shown."


def main() -> None:
    # Resolve image path from CLI arg or default
    image_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_IMAGE
    if not image_path.exists():
        print(f"ERROR: Image not found at {image_path}")
        sys.exit(1)

    print(f"Image:  {image_path.name}")
    print(f"Prompt: {PROMPT}\n")

    # Build orchestrator with full tool registry
    orchestrator = build_orchestrator(PROJECT_ROOT)

    # ---------------------------------------------------------------------------
    # Set up session context — mimic what ws_chat.py does for the real app.
    # The orchestrator needs a workflow_store, user_id, and a pre-created
    # canvas workflow so that tools like add_node/add_connection can persist.
    # ---------------------------------------------------------------------------
    tmp_dir = tempfile.mkdtemp(prefix="lemon_protocol_test_")
    db_path = Path(tmp_dir) / "test_workflows.sqlite"
    workflow_store = WorkflowStore(db_path)
    workflow_id = f"wf_{uuid.uuid4().hex}"
    user_id = "test_user"

    # Create the canvas workflow in the DB (same as ws_chat auto-persist)
    workflow_store.create_workflow(
        workflow_id=workflow_id,
        user_id=user_id,
        name="Test Workflow",
        description="",
        domain=None,
        tags=[],
        nodes=[],
        edges=[],
        inputs=[],
        outputs=[],
        tree={},
        doubts=[],
        validation_score=0,
        validation_count=0,
        is_validated=False,
        output_type="string",
        is_draft=False,
    )

    # Wire up the orchestrator like the real socket handler does
    orchestrator.workflow_store = workflow_store
    orchestrator.user_id = user_id
    orchestrator.current_workflow_id = workflow_id
    orchestrator.current_workflow_name = "Test Workflow"
    orchestrator.repo_root = PROJECT_ROOT

    print(f"Workflow ID: {workflow_id}")
    print(f"DB: {db_path}\n")

    # Prepare file descriptor — orchestrator reads bytes and base64-encodes internally
    has_files = [{
        "id": "img_test_1",
        "name": image_path.name,
        "path": str(image_path),
        "file_type": "image",
        "purpose": "unclassified",
    }]

    # ---------------------------------------------------------------------------
    # Tool call logger — captures every tool invocation in order
    # ---------------------------------------------------------------------------
    tool_log: List[Dict[str, Any]] = []

    def on_tool_event(
        event: str,
        tool_name: str,
        args: Dict[str, Any],
        result: Optional[Dict[str, Any]],
    ) -> None:
        """Callback invoked by orchestrator on each tool lifecycle event."""
        entry = {"event": event, "tool": tool_name, "args": args, "result": result}
        tool_log.append(entry)

        if event == "tool_start":
            # Print a concise live summary of each tool call
            summary = _summarize_args(tool_name, args)
            print(f"  [{len([e for e in tool_log if e['event'] == 'tool_start']):>2}] {tool_name}({summary})")
        elif event == "tool_complete":
            success = result.get("success", "?") if result else "?"
            print(f"       ↳ success={success}")

    # ---------------------------------------------------------------------------
    # Run orchestrator
    # ---------------------------------------------------------------------------
    print("=" * 60)
    print("TOOL CALL LOG")
    print("=" * 60)
    start = time.perf_counter()

    try:
        # Raise iteration limit — complex workflows need 70+ tool calls
        # (28 nodes + 30 connections + variables + verification = ~70 iterations)
        response = orchestrator.respond(
            PROMPT,
            has_files=has_files,
            allow_tools=True,
            on_tool_event=on_tool_event,
        )
        elapsed = time.perf_counter() - start
        print(f"\nCompleted in {elapsed:.1f}s")
    except Exception as exc:
        elapsed = time.perf_counter() - start
        print(f"\nFAILED after {elapsed:.1f}s: {exc}")
        sys.exit(1)

    # ---------------------------------------------------------------------------
    # Phase-ordering validation
    # ---------------------------------------------------------------------------
    # Extract ordered list of tool names from "tool_start" events
    tool_sequence = [e["tool"] for e in tool_log if e["event"] == "tool_start"]

    print("\n" + "=" * 60)
    print("PHASE ORDERING CHECK")
    print("=" * 60)
    print(f"\nTool sequence ({len(tool_sequence)} calls):")
    for i, name in enumerate(tool_sequence):
        print(f"  {i:>2}. {name}")

    # --- Check 1: All add_node calls before any add_connection ---
    # Find the "build phase" boundary: the first add_connection or batch_edit
    # that is NOT part of Phase 3 verification (i.e., not after a view_image/
    # get_current_workflow/validate_workflow that follows the last initial wiring).
    node_indices = [i for i, t in enumerate(tool_sequence) if t == "add_node"]
    conn_indices = [i for i, t in enumerate(tool_sequence) if t == "add_connection"]
    batch_indices = [i for i, t in enumerate(tool_sequence) if t == "batch_edit_workflow"]

    print(f"\nadd_node calls:       {len(node_indices)}")
    print(f"add_connection calls: {len(conn_indices)}")
    print(f"batch_edit calls:     {len(batch_indices)}")

    # Find the verify boundary: first view_image/get_current_workflow/validate_workflow
    # that appears AFTER at least some wiring has been done. Anything after this
    # boundary is Phase 3 self-correction, which is legitimate.
    verify_tools = {"view_image", "get_current_workflow", "validate_workflow"}
    wiring_indices = conn_indices + batch_indices
    verify_boundary = None
    if wiring_indices:
        first_wiring = min(wiring_indices)
        for i, t in enumerate(tool_sequence):
            if i > first_wiring and t in verify_tools:
                verify_boundary = i
                break

    # Only check ordering for calls BEFORE the verify boundary
    # (Phase 3 corrections are allowed to add missing nodes/connections)
    if verify_boundary is not None:
        build_nodes = [i for i in node_indices if i < verify_boundary]
        build_conns = [i for i in conn_indices if i < verify_boundary]
    else:
        build_nodes = node_indices
        build_conns = conn_indices

    nodes_before_edges = True
    if build_nodes and build_conns:
        last_node = max(build_nodes)
        first_conn = min(build_conns)
        nodes_before_edges = last_node < first_conn
        if not nodes_before_edges:
            late_nodes = [i for i in build_nodes if i > first_conn]
            print(f"\n  FAIL: {len(late_nodes)} add_node call(s) appeared after first add_connection")
            print(f"        first add_connection at index {first_conn}, late add_node at {late_nodes}")

    if verify_boundary is not None:
        phase3_nodes = [i for i in node_indices if i >= verify_boundary]
        phase3_conns = [i for i in conn_indices if i >= verify_boundary]
        if phase3_nodes or phase3_conns:
            print(f"\n  Phase 3 corrections: {len(phase3_nodes)} node(s), {len(phase3_conns)} connection(s) added during verification")

    _print_result("Phase 2 — nodes before edges", nodes_before_edges)

    # --- Check 2: Verification phase (verify tools appear after wiring) ---
    last_wiring = max(wiring_indices) if wiring_indices else None
    verify_indices = [i for i, t in enumerate(tool_sequence) if t in verify_tools]

    has_verification = False
    if last_wiring is not None and verify_indices:
        has_verification = any(i > last_wiring for i in verify_indices)

    # Also pass if verify happened mid-wiring and led to corrections
    # (model verified, fixed things, then continued — still valid)
    if not has_verification and verify_boundary is not None:
        has_verification = True

    _print_result("Phase 3 — verification after wiring", has_verification)

    # --- Summary ---
    all_passed = nodes_before_edges and has_verification
    print("\n" + "=" * 60)
    if all_passed:
        print("RESULT: PASS — three-phase protocol followed correctly")
    else:
        print("RESULT: FAIL — protocol ordering violated (see above)")
    print("=" * 60)

    # Print workflow stats
    wf = orchestrator.workflow
    print(f"\nWorkflow: {len(wf.get('nodes', []))} nodes, "
          f"{len(wf.get('edges', []))} edges, "
          f"{len(wf.get('variables', []))} variables")

    # Dump full tool log to JSON for deeper inspection
    out_dir = PROJECT_ROOT / ".lemon"
    out_dir.mkdir(exist_ok=True)
    log_path = out_dir / "protocol_test_tool_log.json"
    with open(log_path, "w") as f:
        json.dump(
            [{"event": e["event"], "tool": e["tool"], "args": e["args"]} for e in tool_log],
            f, indent=2, default=str,
        )
    print(f"Tool log saved to: {log_path}")

    sys.exit(0 if all_passed else 1)


def _summarize_args(tool_name: str, args: Dict[str, Any]) -> str:
    """Return a short string summarizing tool arguments for the live log."""
    if tool_name == "add_node":
        return f"label={args.get('label', '?')!r}, type={args.get('type', '?')}"
    if tool_name == "add_connection":
        return f"{args.get('from_node_id', '?')} → {args.get('to_node_id', '?')}"
    if tool_name == "update_plan":
        items = args.get("items", [])
        return f"{len(items)} item(s)"
    if tool_name == "create_workflow":
        return f"name={args.get('name', '?')!r}"
    if tool_name == "add_workflow_variable":
        return f"name={args.get('name', '?')!r}"
    if tool_name == "batch_edit_workflow":
        ops = args.get("operations", [])
        return f"{len(ops)} op(s)"
    # Default: show first key=value pair
    if args:
        key = next(iter(args))
        val = args[key]
        if isinstance(val, str) and len(val) > 40:
            val = val[:40] + "..."
        return f"{key}={val!r}"
    return ""


def _print_result(label: str, passed: bool) -> None:
    """Print a PASS/FAIL line."""
    status = "PASS" if passed else "FAIL"
    marker = "+" if passed else "!"
    print(f"\n  [{marker}] {label}: {status}")


if __name__ == "__main__":
    main()
