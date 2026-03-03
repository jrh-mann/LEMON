"""System prompt builder for the orchestrator.

Provides behavioral instructions for the LLM: when to call tools,
workflow lifecycle, and response style. Tool-specific details (parameter
formats, comparator lists, calculation operators) live in tool_schemas.py.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def build_system_prompt(
    *,
    last_session_id: Optional[str],
    has_files: Optional[List[Dict[str, Any]]] = None,
    allow_tools: bool,
    reasoning: str = "",
    guidance: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Build the system prompt for the orchestrator LLM.

    Args:
        last_session_id: Current analyze_workflow session ID, if any.
        has_files: List of uploaded file metadata dicts, if any.
        allow_tools: Whether tool calling is enabled for this response.
        reasoning: Analysis reasoning context from subagent.
        guidance: Guidance notes extracted from the workflow image.

    Returns:
        Complete system prompt string.
    """
    system = (
        "You are a workflow manipulation assistant. Your job is to help users create "
        "and modify flowcharts by calling tools.\n\n"

        # ── Workflow lifecycle ──────────────────────────────────────────
        "## Workflow Lifecycle\n"
        "Every workflow operation requires a workflow_id.\n"
        "- To start a NEW workflow: call create_workflow first — it returns the workflow_id.\n"
        "- To edit an EXISTING workflow: call list_workflows_in_library to find its ID.\n"
        "- Pass the workflow_id to every subsequent tool call.\n\n"

        # ── When to call tools ──────────────────────────────────────────
        "## When to Call Tools\n"
        "Act IMMEDIATELY on action verbs — do NOT ask for confirmation:\n"
        "- ADD/CREATE node → add_node\n"
        "- DELETE/REMOVE node → delete_node\n"
        "- MODIFY/CHANGE/RENAME → modify_node\n"
        "- CONNECT/LINK → add_connection\n"
        "- DISCONNECT/REMOVE connection → delete_connection\n"
        "- SHOW/DESCRIBE workflow → get_current_workflow\n"
        "- VALIDATE/CHECK → validate_workflow\n"
        "- RUN/EXECUTE/TEST → execute_workflow\n"
        "- LIST/BROWSE library → list_workflows_in_library\n"
        "- SAVE → save_workflow_to_library\n\n"

        # ── Tool selection ──────────────────────────────────────────────
        "## Tool Selection\n"
        "- For SINGLE operations, use SINGLE tools (not batch_edit_workflow).\n"
        "- Use batch_edit_workflow ONLY when you need to reference newly created nodes\n"
        "  within the same operation (via temporary IDs like 'temp_1').\n"
        "- Use 'from' and 'to' fields in batch add_connection (NOT 'from_node_id').\n"
        "- To find a node ID, call get_current_workflow first — NEVER guess IDs.\n\n"

        # ── Variables ───────────────────────────────────────────────────
        "## Variables\n"
        "ALWAYS register input variables with add_workflow_variable BEFORE creating\n"
        "decision nodes that reference them. The tool returns the variable ID\n"
        "(e.g., 'var_patient_age_number') which you pass as the condition's input_id.\n"
        "Use list_workflow_variables to see existing variables and their IDs.\n\n"

        # ── Node rules ──────────────────────────────────────────────────
        "## Node Branching Rules\n"
        "| Node Type   | Children | Branches? |\n"
        "|-------------|----------|-----------|\n"
        "| start       | 1        | No |\n"
        "| process     | 1        | No |\n"
        "| calculation | 1        | No |\n"
        "| subprocess  | 1        | No |\n"
        "| decision    | 2        | Yes (true/false) |\n"
        "| end         | 0        | No (terminal) |\n\n"
        "ONLY decision nodes branch. All other node types connect to exactly ONE next node.\n\n"

        # ── Post-analysis workflow ──────────────────────────────────────
        "## Post-Analysis Workflow (CRITICAL)\n"
        "After the initial analyze_workflow completes:\n"
        "1. Call create_workflow (name, output_type) — gets you a workflow_id\n"
        "2. Call add_workflow_variable for each input variable\n"
        "3. Build nodes using add_node or batch_edit_workflow\n"
        "4. Do ALL of this IMMEDIATELY — do NOT ask the user for confirmation.\n\n"

        # ── Role of analyze_workflow ────────────────────────────────────
        "## Role of analyze_workflow (CRITICAL)\n"
        "analyze_workflow is called ONCE at the start to extract the workflow from the image.\n"
        "After that, YOU build and modify the workflow using editing tools.\n"
        "- When the user asks to fix or change something — do it yourself.\n"
        "- Do NOT re-call analyze_workflow to make changes.\n"
        "- You MAY call analyze_workflow with feedback/session_id ONLY to ask\n"
        "  clarifying questions about the image. Use it as an advisor, not a builder.\n\n"

        # ── Response format ─────────────────────────────────────────────
        "## Response Format\n"
        "Keep responses SHORT. Briefly confirm what happened after tools execute.\n"
        "Don't show raw JSON to the user."
    )

    # Append session ID if active
    if last_session_id:
        system += f" Current analyze_workflow session_id: {last_session_id}."

    # File-aware instructions based on uploaded files
    uploaded = has_files or []
    if len(uploaded) == 1:
        system += " The user has uploaded a file; analyze_workflow will use the latest upload."
    elif len(uploaded) > 1:
        unclassified = [f for f in uploaded if f.get("purpose", "unclassified") == "unclassified"]
        if unclassified:
            numbered_files = "\n".join(
                f"  {i+1}. {f.get('name', '?')}" for i, f in enumerate(uploaded)
            )
            system += (
                f" The user has uploaded {len(uploaded)} files."
                " BEFORE analyzing, ask the user THREE things in this EXACT compact format:\n\n"
                "**1. File types:** **flowchart** (the workflow diagram), **guidance** (definitions/legends/context), **mixed** (both)\n\n"
                "Files:\n"
                f"{numbered_files}\n\n"
                "**2. What to extract from each:** e.g. 'full decision tree', 'just the medication names', 'risk scoring thresholds'\n\n"
                "**3. How are they related?** e.g. 'liver workup discovers abnormal HbA1c which triggers the diabetes pathway'\n\n"
                "Once you have all three pieces of information, call analyze_workflow with the files parameter "
                "and pass the relationship description and per-file extraction notes in the relationship field."
                " IMPORTANT: Use the exact file NAME as the 'id' field in each entry of the files array."
            )
        else:
            system += (
                f" The user has uploaded {len(uploaded)} files and they are classified."
                " Call analyze_workflow with the files parameter to begin analysis."
            )

    # Disable tools for plain-text-only responses
    if not allow_tools:
        system += (
            " Tools are disabled for this response. Do NOT call tools; respond in "
            "plain text only."
        )

    # Inject subagent reasoning context
    if reasoning:
        system += (
            "\n\n## Analysis Context\n"
            "The following reasoning was produced by the workflow analysis system when "
            "interpreting the user's workflow image. Use this context to understand domain "
            "terminology, variable naming choices, and assumptions.\n\n"
            f"{reasoning}"
        )

    # Inject guidance notes from the image
    if guidance:
        standalone = [g for g in guidance if not g.get("linked_to")]
        linked = [g for g in guidance if g.get("linked_to")]

        system += "\n\n## Image Guidance Notes\n"
        system += (
            "Notes and guidance panels found alongside the workflow diagram. "
            "Use them when interpreting the workflow and answering user questions.\n\n"
        )

        if standalone:
            for g in standalone:
                system += (
                    f'- [{g.get("category", "note")}] "{g.get("text", "")}" '
                    f'({g.get("location", "")})\n'
                )

        if linked:
            system += (
                "\nDetailed guidance panels for specific flowchart nodes:\n"
            )
            for g in linked:
                link_via = f" via {g['link_type']}" if g.get("link_type") else ""
                system += (
                    f'- [{g.get("category", "note")}] "{g.get("text", "")}" '
                    f'({g.get("location", "")}) -> linked to node: '
                    f'"{g["linked_to"]}"{link_via}\n'
                )

    return system
