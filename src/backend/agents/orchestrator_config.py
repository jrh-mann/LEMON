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
                        "input_ref": {
                            "type": "string",
                            "description": "Optional: name of workflow input this node checks (case-insensitive)",
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
                        "input_ref": {
                            "type": "string",
                            "description": "Optional: name of workflow input this node checks (case-insensitive)",
                        },
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
                                "List of operations. Each operation is an object with 'op' field plus operation-specific fields.\n\n"
                                "add_node: {op, type, label, id (temp ID for referencing), x, y}\n"
                                "modify_node: {op, node_id, label?, type?, x?, y?}\n"
                                "delete_node: {op, node_id}\n"
                                "add_connection: {op, from (node_id or temp_id), to (node_id or temp_id), label}\n"
                                "delete_connection: {op, from (node_id), to (node_id)}"
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
                                    },
                                    "id": {"type": "string", "description": "Temp ID for new nodes (e.g., temp_1)"},
                                    "type": {"type": "string", "enum": ["start", "process", "decision", "subprocess", "end"]},
                                    "label": {"type": "string"},
                                    "x": {"type": "number"},
                                    "y": {"type": "number"},
                                    "input_ref": {"type": "string", "description": "Optional: name of workflow input (case-insensitive)"},
                                    "node_id": {"type": "string", "description": "Existing node ID"},
                                    "from": {"type": "string", "description": "Source node ID or temp ID"},
                                    "to": {"type": "string", "description": "Target node ID or temp ID"},
                                },
                                "required": ["op"],
                            },
                        }
                    },
                    "required": ["operations"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "add_workflow_input",
                "description": (
                    "Register an input parameter for the workflow. This input will appear in the Inputs tab "
                    "where users can provide values. Use this when the workflow needs data from users (e.g., "
                    "'Patient Age', 'Email Address', 'Order Amount')."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Human-readable input name (e.g., 'Patient Age', 'Email Address')",
                        },
                        "type": {
                            "type": "string",
                            "enum": ["string", "number", "boolean", "enum"],
                            "description": "Input type: 'string', 'number', 'boolean', or 'enum'",
                        },
                        "description": {
                            "type": "string",
                            "description": "Optional description of what this input represents",
                        },
                        "enum_values": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "For enum type: array of allowed values (e.g., ['Male', 'Female', 'Other'])",
                        },
                        "range_min": {
                            "type": "number",
                            "description": "For number type: minimum allowed value",
                        },
                        "range_max": {
                            "type": "number",
                            "description": "For number type: maximum allowed value",
                        },
                    },
                    "required": ["name", "type"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_workflow_inputs",
                "description": (
                    "Get all registered workflow inputs. Returns the list of inputs that have been "
                    "registered with add_workflow_input. Use this to see what inputs are available "
                    "before referencing them in nodes."
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
                "name": "remove_workflow_input",
                "description": (
                    "Remove a registered workflow input by name (case-insensitive). "
                    "If the input is referenced by nodes, deletion will fail by default. "
                    "Use force=true to cascade delete (automatically removes input_ref from all nodes)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name of the input to remove (case-insensitive)",
                        },
                        "force": {
                            "type": "boolean",
                            "description": "If true, removes input even if referenced by nodes (cascade delete). Default: false",
                        },
                    },
                    "required": ["name"],
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
        "You are a workflow manipulation assistant. Your job is to help users create and modify flowcharts by calling tools.\n\n"
        "## CRITICAL: When to Call Tools\n"
        "ALWAYS call tools immediately when the user uses action verbs:\n"
        "- ADD/CREATE (node) → call add_node\n"
        "- DELETE/REMOVE (node) → call delete_node\n"
        "- DELETE/REMOVE (connection/edge) → call delete_connection\n"
        "- DISCONNECT/UNLINK → call delete_connection\n"
        "- MODIFY/CHANGE/UPDATE/RENAME → call modify_node\n"
        "- CONNECT/LINK → call add_connection\n"
        "- WHAT/SHOW/LIST/DESCRIBE → call get_current_workflow\n\n"
        "DO NOT ask for confirmation. DO NOT clarify unless the request is truly ambiguous (e.g., 'add a node' without any description). "
        "If the user says 'add a start node', immediately call add_node. "
        "If the user says 'delete the validation node', immediately call get_current_workflow to find it, then delete_node. "
        "If the user says 'remove the connection from A to B', immediately call delete_connection.\n\n"
        "## Keep It Simple\n"
        "For SINGLE operations, use SINGLE tools:\n"
        "- 'add a process node' = 1x add_node (NOT batch_edit_workflow)\n"
        "- 'delete node X' = 1x delete_node\n"
        "- 'connect A to B' = 1x add_connection\n"
        "- 'remove connection from A to B' = 1x delete_connection\n\n"
        "DO NOT use batch_edit_workflow for simple single operations.\n"
        "DO NOT call get_current_workflow before every operation unless you need to find a node ID.\n\n"
        "## Multiple Tool Calls (Only When Explicitly Requested)\n"
        "Call multiple tools ONLY when the user explicitly requests multiple operations:\n"
        "- 'Create start → process → end' = 3x add_node + 2x add_connection calls\n"
        "- 'Add 3 validation nodes' = 3x add_node calls\n"
        "- 'Delete node X and reconnect Y to Z' = delete_node + add_connection\n\n"
        "If the user asks for ONE thing, call ONE tool. Don't overthink it.\n\n"
        "## Working with Node IDs\n"
        "Nodes have IDs like 'node_abc123'. When the user refers to nodes by label:\n"
        "1. Call get_current_workflow() to see all nodes\n"
        "2. Find the node ID by matching the label\n"
        "3. Use that ID in your tool calls\n"
        "NEVER guess node IDs.\n\n"
        "## Decision Nodes (ONLY Exception to Single Tool Rule)\n"
        "Decision nodes are the ONLY case where you MUST use batch_edit_workflow:\n"
        "```\n"
        "operations=[\n"
        "  {\"op\": \"add_node\", \"id\": \"temp_decision\", \"type\": \"decision\", \"label\": \"Check Age\", \"x\": 100, \"y\": 100},\n"
        "  {\"op\": \"add_node\", \"id\": \"temp_true\", \"type\": \"end\", \"label\": \"Adult\", \"x\": 50, \"y\": 200},\n"
        "  {\"op\": \"add_node\", \"id\": \"temp_false\", \"type\": \"end\", \"label\": \"Minor\", \"x\": 150, \"y\": 200},\n"
        "  {\"op\": \"add_connection\", \"from\": \"temp_decision\", \"to\": \"temp_true\", \"label\": \"true\"},\n"
        "  {\"op\": \"add_connection\", \"from\": \"temp_decision\", \"to\": \"temp_false\", \"label\": \"false\"}\n"
        "]\n"
        "```\n"
        "CRITICAL: Use 'from' and 'to' fields (NOT 'from_node_id'/'to_node_id') in batch add_connection operations.\n\n"
        "## Response Format\n"
        "After tools execute, briefly confirm what happened: 'Added start node', 'Deleted validation node', 'Connected X to Y'.\n"
        "Keep responses SHORT. Don't show raw JSON to the user.\n\n"
        "## Reading Workflow State\n"
        "When the user asks 'what's on the canvas?' or 'what nodes do we have?', call get_current_workflow and describe the nodes/edges you see.\n\n"
        "## Workflow Inputs (CRITICAL)\n"
        "WHENEVER you see a decision node that checks a condition on data, you MUST register that data as a workflow input:\n"
        "1. Identify what data the decision checks (e.g., 'Patient Age', 'Order Amount', 'Email Valid')\n"
        "2. Call add_workflow_input to register it with appropriate type (string/number/boolean/enum)\n"
        "3. Then add the decision node with input_ref parameter pointing to that input name\n\n"
        "Examples:\n"
        "- User: 'Add decision: is patient over 60?'\n"
        "  → Call add_workflow_input(name='Patient Age', type='number')\n"
        "  → Then add_node(type='decision', label='Patient over 60?', input_ref='Patient Age')\n\n"
        "- User: 'Create workflow for processing orders based on amount'\n"
        "  → Call add_workflow_input(name='Order Amount', type='number')\n"
        "  → Then create decision nodes with input_ref='Order Amount'\n\n"
        "- User: 'Check if email is valid'\n"
        "  → Call add_workflow_input(name='Email Address', type='string')\n"
        "  → Then add_node(type='decision', label='Email valid?', input_ref='Email Address')\n\n"
        "ALWAYS register inputs BEFORE creating nodes that reference them.\n"
        "Use list_workflow_inputs to see what inputs already exist.\n"
        "Input names are case-insensitive when referencing (e.g., 'patient age' matches 'Patient Age').\n\n"
        "## Removing Workflow Inputs (CRITICAL)\n"
        "When removing workflow inputs with remove_workflow_input:\n"
        "1. By default, deletion FAILS if nodes still reference the input\n"
        "2. If deletion fails, ask the user: 'This input is referenced by N node(s). Should I:\n"
        "   a) Remove references manually (you'll need to update/delete those nodes), or\n"
        "   b) Force delete (automatically removes input_ref from all nodes)?'\n"
        "3. ONLY use force=true if the user explicitly approves cascade deletion\n"
        "4. NEVER use force=true without asking the user first\n\n"
        "Example:\n"
        "- Tool fails: 'Cannot remove input 'Patient Age': referenced by 3 nodes'\n"
        "- You respond: 'This input is used by 3 nodes (Age Check, Eligibility, Treatment). "
        "Would you like me to force delete it (which will remove the references from these nodes)?'\n"
        "- User: 'Yes, force delete it'\n"
        "- You call: remove_workflow_input(name='Patient Age', force=true)"
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
