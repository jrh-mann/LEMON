"""Prompt and tool configuration for the orchestrator."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def tool_descriptions() -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "analyze_workflow",
                "description": (
                    "Analyze the most recently uploaded workflow image. "
                    "Returns JSON with inputs, outputs, tree, doubts, plus session_id. "
                    "Use session_id + feedback to refine a prior analysis. "
                    "If no image has been uploaded, the tool will report that."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "string",
                            "description": "Optional session id to continue a prior analysis.",
                        },
                        "feedback": {
                            "type": "string",
                            "description": "Optional feedback to refine the analysis.",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "publish_latest_analysis",
                "description": (
                    "Load the most recent workflow analysis and return it for rendering "
                    "on the canvas."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_current_workflow",
                "description": (
                    "Get the current workflow displayed on the canvas as JSON (nodes and edges). "
                    "Returns workflow structure with semantic descriptions to help you understand "
                    "node IDs and connections. Use this before making changes to see what exists."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "add_node",
                "description": (
                    "Add a new node (block) to the workflow. Returns the created node with a real ID. "
                    "Note: Decision nodes require 2 branches to be valid - use batch_edit_workflow "
                    "to add a decision node with its branches atomically."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["start", "process", "decision", "subprocess", "end"],
                            "description": "Node type",
                        },
                        "label": {
                            "type": "string",
                            "description": "Display text for the node",
                        },
                        "x": {
                            "type": "number",
                            "description": "X coordinate (optional, auto-positions if omitted)",
                        },
                        "y": {
                            "type": "number",
                            "description": "Y coordinate (optional, auto-positions if omitted)",
                        },
                    },
                    "required": ["type", "label"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "modify_node",
                "description": (
                    "Update an existing node's properties (label, type, position). "
                    "You must know the node_id first - call get_current_workflow to find it."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_id": {
                            "type": "string",
                            "description": "ID of the node to modify",
                        },
                        "label": {
                            "type": "string",
                            "description": "New label text",
                        },
                        "type": {
                            "type": "string",
                            "enum": ["start", "process", "decision", "subprocess", "end"],
                            "description": "New node type",
                        },
                        "x": {"type": "number", "description": "New X coordinate"},
                        "y": {"type": "number", "description": "New Y coordinate"},
                    },
                    "required": ["node_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_node",
                "description": (
                    "Remove a node and all connected edges from the workflow. "
                    "Validates that the result is still a valid workflow structure."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_id": {
                            "type": "string",
                            "description": "ID of the node to delete",
                        }
                    },
                    "required": ["node_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "add_connection",
                "description": (
                    "Create an edge connecting two nodes. For decision nodes, use label "
                    "'true' or 'false'. Validates that the connection creates a valid workflow."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "from_node_id": {
                            "type": "string",
                            "description": "Source node ID",
                        },
                        "to_node_id": {
                            "type": "string",
                            "description": "Target node ID",
                        },
                        "label": {
                            "type": "string",
                            "description": "Edge label (e.g., 'true', 'false', or empty)",
                        },
                    },
                    "required": ["from_node_id", "to_node_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_connection",
                "description": (
                    "Remove an edge between two nodes. Validates that removing the "
                    "connection doesn't create an invalid workflow structure."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "from_node_id": {
                            "type": "string",
                            "description": "Source node ID",
                        },
                        "to_node_id": {
                            "type": "string",
                            "description": "Target node ID",
                        },
                    },
                    "required": ["from_node_id", "to_node_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "batch_edit_workflow",
                "description": (
                    "Apply multiple workflow changes in a single atomic operation. All changes "
                    "are validated together - if any fail, none are applied. Use this for: "
                    "(1) Adding decision nodes with their branches atomically, "
                    "(2) Making multiple related changes that should succeed or fail together. "
                    "Supports temp IDs: use 'temp_X' for new nodes, then reference them in "
                    "subsequent operations. They'll be replaced with real UUIDs."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operations": {
                            "type": "array",
                            "description": (
                                "List of operations. Each has 'op' field (add_node, modify_node, "
                                "delete_node, add_connection, delete_connection) plus operation-specific fields."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "op": {
                                        "type": "string",
                                        "enum": [
                                            "add_node",
                                            "modify_node",
                                            "delete_node",
                                            "add_connection",
                                            "delete_connection",
                                        ],
                                    }
                                },
                                "required": ["op"],
                            },
                        }
                    },
                    "required": ["operations"],
                },
            },
        },
    ]


def build_system_prompt(
    *,
    last_session_id: Optional[str],
    has_image: bool,
    allow_tools: bool,
) -> str:
    system = (
        "You are the orchestrator for a system that ingests flowchart images "
        "and converts them into structured data, ultimately used to generate "
        "Python programs. Mission: help users understand, refine, and evolve "
        "their flowcharts; be proactive and helpful; only perform analysis or "
        "modifications through tools when explicitly requested or confirmed. "
        "Core rules: do not edit JSON directly; all changes go through tool "
        "calls. Prefer clarifying questions before any modification to the "
        "JSON/tree. If the user explicitly requests analysis of an image, tell the user what ur doing and then call "
        "the tool. Clarifying questions are allowed "
        "without tool use. "
        "\n\n"
        "## Working with Workflow IDs\n"
        "Nodes and edges have unique IDs like 'node_abc123'. When the user refers to nodes "
        "by label (e.g., 'the age check'), you MUST: (1) First call get_current_workflow() "
        "to see all nodes, (2) Match the user's description to node IDs using labels, "
        "(3) Use the node IDs in subsequent tool calls. NEVER guess or make up node IDs. "
        "Always check the workflow first.\n\n"
        "## Workflow Manipulation\n"
        "Use batch_edit_workflow for: (1) Adding decision nodes (they need 2 branches atomically), "
        "(2) Multiple related changes that should succeed/fail together. Use temp IDs like 'temp_1' "
        "for new nodes, then reference them in later operations within the same batch. "
        "Individual tools (add_node, modify_node, etc.) work for single changes. "
        "All tools validate before applying - if validation fails, explain the error to the user.\n\n"
        "Tool use policy: tools are required for analyzing a new image or "
        "applying JSON/tree changes. Tool calls are executed via MCP. Use tools "
        "when needed, but you may respond in plain text for discussion and guidance. "
        "After tool results are provided, decide if additional tool calls are needed "
        "to satisfy the user's request. If so, call them; otherwise respond in plain "
        "text only. Multiple tool calls may be required in a single turn. Do not show "
        "raw tool JSON to the user; summarize "
        "ONLY inputs, outputs, and doubts from the tool result. Tool output may "
        "omit the tree; state what is missing and ask how to proceed. "
        "Decision flow: if the user explicitly says analyze [image_name], apply "
        "changes, add/update/remove node, modify/merge/reorder/connect, generate "
        "structured data, or similar, call the tool. If ambiguous, ask "
        "clarifying questions first. For discussion, reviews, explanations, "
        "planning, proposing edits, or best-practice advice, stay in plain text "
        "and do not call tools. Clarifying questions before action: for edits, "
        "confirm exact nodes/branches, desired outcome, acceptance criteria, "
        "and whether minor or major. For continued sessions, ask for or reuse "
        "session_id and request feedback instead of re-running image analysis. "
        "Interaction style: concise, friendly, solution-oriented; offer options "
        "with pros/cons; suggest validation steps without calling tools unless "
        "requested. Formatting: avoid heavy formatting; bullets are fine; keep "
        "outputs machine-parseable when emitting tool JSON; otherwise plain "
        "text. Error handling: if a tool fails or returns incomplete data, "
        "explain what is missing, propose remedies, ask how to proceed; if the "
        "user says don't call tools, stay in plain text unless they reverse it."
    )
    if last_session_id:
        system += f" Current analyze_workflow session_id: {last_session_id}."
    if has_image:
        system += " The user has uploaded an image; analyze_workflow will use the latest upload."
    if not allow_tools:
        system += (
            " Tools are disabled for this response. Do NOT call tools; respond in "
            "plain text only."
        )
    return system
