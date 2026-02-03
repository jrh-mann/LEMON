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
        # === NEW: create_workflow must be called first ===
        {
            "type": "function",
            "function": {
                "name": "create_workflow",
                "description": (
                    "Create a new workflow in the user's library. ALWAYS call this FIRST before "
                    "adding nodes or variables to a new workflow. Returns a workflow_id that must "
                    "be passed to ALL subsequent tool calls (add_node, add_connection, etc.). "
                    "The workflow starts empty and must be built step by step."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name for the workflow (e.g., 'BMI Calculator', 'Loan Approval')",
                        },
                        "description": {
                            "type": "string",
                            "description": "Description of what the workflow does",
                        },
                        "output_type": {
                            "type": "string",
                            "enum": ["string", "int", "float", "bool", "json"],
                            "description": "Type of value the workflow returns when executed",
                        },
                        "domain": {
                            "type": "string",
                            "description": "Domain/category for the workflow (e.g., 'Healthcare', 'Finance')",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of tags for categorization",
                        },
                    },
                    "required": ["name", "output_type"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_current_workflow",
                "description": (
                    "Get a workflow's current state as JSON (nodes and edges). "
                    "Returns workflow structure with semantic descriptions to help you understand "
                    "node IDs and connections. Use this before making changes to see what exists. "
                    "Requires workflow_id."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "ID of the workflow to retrieve (from create_workflow)",
                        },
                    },
                    "required": ["workflow_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "add_node",
                "description": (
                    "Add a new node (block) to a workflow. Returns the created node with a real ID. "
                    "Requires workflow_id. "
                    "Note: Decision nodes should have 2 branches (true/false). You can add them separately "
                    "with add_node + add_connection, or use batch_edit_workflow to create the decision + branches "
                    "atomically with temporary IDs.\n\n"
                    "For SUBPROCESS nodes (subflows): Use subprocess type to call another workflow. "
                    "You MUST provide subworkflow_id, input_mapping, and output_variable. "
                    "The subworkflow's output will be available as a new input variable that "
                    "subsequent decision nodes can reference."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "ID of the workflow to add the node to (from create_workflow)",
                        },
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
                        "output_type": {
                            "type": "string",
                            "enum": ["string", "int", "float", "bool", "json"],
                            "description": "For 'end' nodes: data type of the output.",
                        },
                        "output_template": {
                            "type": "string",
                            "description": "For 'end' nodes: Python f-string template (e.g. 'Result: {Age}').",
                        },
                        "output_value": {
                            "type": "string",
                            "description": "For 'end' nodes: Static value (or JSON string).",
                        },
                        "condition": {
                            "type": "object",
                            "description": (
                                "REQUIRED for 'decision' nodes: Structured condition to evaluate. "
                                "Must include input_id (e.g., 'input_age_int'), comparator, and value. "
                                "See system prompt for valid comparators by input type."
                            ),
                            "properties": {
                                "input_id": {"type": "string", "description": "ID of the workflow input to check"},
                                "comparator": {
                                    "type": "string",
                                    "enum": [
                                        "eq", "neq", "lt", "lte", "gt", "gte", "within_range",
                                        "is_true", "is_false",
                                        "str_eq", "str_neq", "str_contains", "str_starts_with", "str_ends_with",
                                        "date_eq", "date_before", "date_after", "date_between",
                                        "enum_eq", "enum_neq"
                                    ],
                                    "description": "Comparison operator"
                                },
                                "value": {"description": "Value to compare against"},
                                "value2": {"description": "Second value for range comparators (within_range, date_between)"}
                            },
                            "required": ["input_id", "comparator", "value"]
                        },
                        "subworkflow_id": {
                            "type": "string",
                            "description": "For 'subprocess' nodes: ID of the workflow to call as a subflow.",
                        },
                        "input_mapping": {
                            "type": "object",
                            "description": "For 'subprocess' nodes: Maps parent input names to subworkflow input names. Example: {\"ParentAge\": \"SubAge\", \"ParentIncome\": \"SubIncome\"}",
                            "additionalProperties": {"type": "string"},
                        },
                        "output_variable": {
                            "type": "string",
                            "description": "For 'subprocess' nodes: Name for the variable that will hold the subworkflow's output. This becomes available as a new input for subsequent nodes.",
                        },
                    },
                    "required": ["workflow_id", "type", "label"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "modify_node",
                "description": (
                    "Update an existing node's properties (label, type, position). "
                    "Requires workflow_id. "
                    "You must know the node_id first - call get_current_workflow to find it.\n\n"
                    "For SUBPROCESS nodes: You can update subworkflow_id, input_mapping, and output_variable.\n"
                    "For DECISION nodes: You can update the condition."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "ID of the workflow containing the node",
                        },
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
                        "output_type": {
                            "type": "string",
                            "enum": ["string", "int", "float", "bool", "json"],
                            "description": "For 'end' nodes: data type of the output.",
                        },
                        "output_template": {
                            "type": "string",
                            "description": "For 'end' nodes: Python f-string template (e.g. 'Result: {Age}').",
                        },
                        "output_value": {
                            "type": "string",
                            "description": "For 'end' nodes: Static value (or JSON string).",
                        },
                        "condition": {
                            "type": "object",
                            "description": (
                                "For 'decision' nodes: Structured condition to evaluate. "
                                "See add_node for full schema details."
                            ),
                            "properties": {
                                "input_id": {"type": "string"},
                                "comparator": {"type": "string"},
                                "value": {},
                                "value2": {}
                            },
                            "required": ["input_id", "comparator", "value"]
                        },
                        "subworkflow_id": {
                            "type": "string",
                            "description": "For 'subprocess' nodes: ID of the workflow to call.",
                        },
                        "input_mapping": {
                            "type": "object",
                            "description": "For 'subprocess' nodes: Maps parent input names to subworkflow input names.",
                            "additionalProperties": {"type": "string"},
                        },
                        "output_variable": {
                            "type": "string",
                            "description": "For 'subprocess' nodes: Name for the output variable.",
                        },
                    },
                    "required": ["workflow_id", "node_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_node",
                "description": (
                    "Remove a node and all connected edges from the workflow. "
                    "Requires workflow_id. "
                    "Validates that the result is still a valid workflow structure."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "ID of the workflow containing the node",
                        },
                        "node_id": {
                            "type": "string",
                            "description": "ID of the node to delete",
                        }
                    },
                    "required": ["workflow_id", "node_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "add_connection",
                "description": (
                    "Create an edge connecting two nodes. For decision nodes, use label "
                    "'true' or 'false'. Requires workflow_id. "
                    "Validates that the connection creates a valid workflow."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "ID of the workflow to add the connection to",
                        },
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
                    "required": ["workflow_id", "from_node_id", "to_node_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_connection",
                "description": (
                    "Remove an edge between two nodes. Requires workflow_id. "
                    "Validates that removing the connection doesn't create an invalid workflow structure."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "ID of the workflow containing the connection",
                        },
                        "from_node_id": {
                            "type": "string",
                            "description": "Source node ID",
                        },
                        "to_node_id": {
                            "type": "string",
                            "description": "Target node ID",
                        },
                    },
                    "required": ["workflow_id", "from_node_id", "to_node_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "batch_edit_workflow",
                "description": (
                    "Apply multiple workflow changes in a single atomic operation. Requires workflow_id. "
                    "All changes are validated together - if any fail, none are applied. "
                    "\n\n"
                    "PRIMARY USE CASE - Temporary ID References: "
                    "When you need to create nodes and immediately connect them in the same operation, "
                    "use temporary IDs (like 'temp_decision', 'temp_start') instead of real node IDs. "
                    "The tool automatically maps temp IDs to real UUIDs and updates all references. "
                    "\n\n"
                    "Common scenarios: "
                    "(1) Decision nodes with branches - create decision + 2 branch nodes + 2 connections atomically, "
                    "(2) Node chains - create start->process->end with connections in one operation, "
                    "(3) Complex multi-step changes that should succeed or fail together, "
                    "(4) Subprocess nodes with their connections - create subprocess and connect it atomically."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "ID of the workflow to edit",
                        },
                        "operations": {
                            "type": "array",
                            "description": (
                                "List of operations. Each operation is an object with 'op' field plus operation-specific fields.\n\n"
                                "add_node: {op, type, label, id (temp ID for referencing), x, y, condition?, output_type?, output_template?, output_value?, subworkflow_id?, input_mapping?, output_variable?}\n"
                                "modify_node: {op, node_id, label?, type?, x?, y?, condition?, output_type?, output_template?, output_value?, subworkflow_id?, input_mapping?, output_variable?}\n"
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
                                    "condition": {
                                        "type": "object",
                                        "description": "For decision nodes: {input_id, comparator, value, value2?}",
                                        "properties": {
                                            "input_id": {"type": "string"},
                                            "comparator": {"type": "string"},
                                            "value": {},
                                            "value2": {}
                                        }
                                    },
                                    "output_type": {"type": "string", "enum": ["string", "int", "float", "bool", "json"]},
                                    "output_template": {"type": "string"},
                                    "output_value": {"type": "string"},
                                    "subworkflow_id": {"type": "string", "description": "For subprocess: workflow ID to call"},
                                    "input_mapping": {"type": "object", "description": "For subprocess: parent->subworkflow input mapping"},
                                    "output_variable": {"type": "string", "description": "For subprocess: name for output variable"},
                                    "node_id": {"type": "string", "description": "Existing node ID"},
                                    "from": {"type": "string", "description": "Source node ID or temp ID"},
                                    "to": {"type": "string", "description": "Target node ID or temp ID"},
                                },
                                "required": ["op"],
                            },
                        }
                    },
                    "required": ["workflow_id", "operations"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "validate_workflow",
                "description": (
                    "Check if a workflow is valid. Requires workflow_id. "
                    "Reports errors like disconnected nodes, missing branches, or unreachable paths. "
                    "Use this when the user asks to validate, check, or verify the workflow."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "ID of the workflow to validate",
                        },
                    },
                    "required": ["workflow_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "execute_workflow",
                "description": (
                    "Run a workflow with the given input values and return the result. "
                    "Requires workflow_id. "
                    "Provide input values as a JSON object mapping variable names to their values. "
                    "Returns the output, the path of nodes visited, and the final variable context. "
                    "Use this when the user asks to run, execute, test, or try the workflow."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "ID of the workflow to execute",
                        },
                        "input_values": {
                            "type": "object",
                            "description": (
                                "Input values keyed by variable name or ID. "
                                "Example: {\"Age\": 25, \"Smoker\": false}"
                            ),
                        },
                    },
                    "required": ["workflow_id", "input_values"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "add_workflow_variable",
                "description": (
                    "Register a user-input variable for a workflow. Requires workflow_id. "
                    "This variable will appear in the Variables tab under 'Inputs' where users "
                    "provide values at execution time. Use this when the workflow needs data from "
                    "users (e.g., 'Patient Age', 'Email Address', 'Order Amount'). "
                    "Returns the variable with its ID (format: var_{name}_{type}, e.g., 'var_patient_age_int'). "
                    "NOTE: For subprocess outputs, use the output_variable parameter when adding a subprocess node - "
                    "those are automatically registered as derived variables."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "ID of the workflow to add the variable to",
                        },
                        "name": {
                            "type": "string",
                            "description": "Human-readable variable name (e.g., 'Patient Age', 'Email Address')",
                        },
                        "type": {
                            "type": "string",
                            "enum": ["string", "number", "boolean", "enum"],
                            "description": "Variable type: 'string', 'number', 'boolean', or 'enum'",
                        },
                        "description": {
                            "type": "string",
                            "description": "Optional description of what this variable represents",
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
                    "required": ["workflow_id", "name", "type"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_workflow_variables",
                "description": (
                    "Get all registered workflow variables. Requires workflow_id. "
                    "Returns both user-input variables (source='input') and derived variables "
                    "(e.g., subprocess outputs with source='subprocess'). "
                    "Variable IDs use the format var_{name}_{type} for inputs, var_sub_{name}_{type} for subprocess outputs. "
                    "Use this to see what variables are available before referencing them in decision nodes."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "ID of the workflow to list variables from",
                        },
                    },
                    "required": ["workflow_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "remove_workflow_variable",
                "description": (
                    "Remove a registered workflow input variable by name (case-insensitive). "
                    "Requires workflow_id. "
                    "If the variable is used in decision node conditions, deletion will fail by default. "
                    "Use force=true to cascade delete (automatically clears conditions from affected nodes)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "ID of the workflow containing the variable",
                        },
                        "name": {
                            "type": "string",
                            "description": "Name of the variable to remove (case-insensitive)",
                        },
                        "force": {
                            "type": "boolean",
                            "description": "If true, removes variable even if referenced by nodes (cascade delete). Default: false",
                        },
                    },
                    "required": ["workflow_id", "name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "modify_workflow_variable",
                "description": (
                    "Modify an existing workflow variable's properties (type, name, description, range, enum values). "
                    "Requires workflow_id. "
                    "CRITICAL USE CASE: Correct auto-inferred types for subprocess outputs. "
                    "When a subprocess node is added, the output variable type is inferred from the subworkflow. "
                    "If this is wrong (e.g., 'string' instead of 'int'), use this tool to fix it. "
                    "WARNING: Changing the type also changes the variable ID, so decision nodes using the old ID must be updated."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "ID of the workflow containing the variable",
                        },
                        "name": {
                            "type": "string",
                            "description": "Name of the variable to modify (case-insensitive match)",
                        },
                        "new_type": {
                            "type": "string",
                            "enum": ["string", "number", "integer", "boolean", "enum", "date"],
                            "description": "New type for the variable. 'number' = float, 'integer' = int.",
                        },
                        "new_name": {
                            "type": "string",
                            "description": "New name for the variable (optional)",
                        },
                        "description": {
                            "type": "string",
                            "description": "New description (optional)",
                        },
                        "enum_values": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "For enum type: array of allowed values",
                        },
                        "range_min": {
                            "type": "number",
                            "description": "For number/integer types: minimum allowed value",
                        },
                        "range_max": {
                            "type": "number",
                            "description": "For number/integer types: maximum allowed value",
                        },
                    },
                    "required": ["workflow_id", "name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_workflows_in_library",
                "description": (
                    "List all workflows in the user's library, PLUS the current canvas workflow (even if unsaved). "
                    "Returns workflow metadata including name, description, domain, tags, status, "
                    "validation status, and input/output information. "
                    "Status values: 'saved' (in DB), 'current' (on canvas and in DB), 'current (unsaved)' (on canvas, not in DB). "
                    "Use this to: check if similar workflows already exist before creating new ones, "
                    "find the workflow_id of an existing workflow, or get the ID of the current canvas workflow."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "search_query": {
                            "type": "string",
                            "description": "Optional text to search for in workflow names, descriptions, or domains",
                        },
                        "domain": {
                            "type": "string",
                            "description": "Optional domain filter (e.g., 'Healthcare', 'Finance')",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of workflows to return (default: 50, max: 100)",
                            "minimum": 1,
                            "maximum": 100,
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "save_workflow_to_library",
                "description": (
                    "Save a draft workflow to the user's permanent library. "
                    "Drafts are workflows you've created that haven't been explicitly saved yet. "
                    "Once saved, the workflow appears in the user's browse library. "
                    "Use this when the user asks to save the workflow, confirms they want to keep it, "
                    "or says the workflow is complete and ready to use."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "ID of the workflow to save (from create_workflow)",
                        },
                        "name": {
                            "type": "string",
                            "description": "Optional new name for the workflow",
                        },
                        "description": {
                            "type": "string",
                            "description": "Optional new description",
                        },
                        "domain": {
                            "type": "string",
                            "description": "Optional domain/category",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional list of tags",
                        },
                    },
                    "required": ["workflow_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "set_workflow_output",
                "description": (
                    "Declare a workflow's output with a name and REQUIRED type. "
                    "Requires workflow_id. "
                    "The output type is critical for subprocess variable inference - when this workflow "
                    "is used as a subprocess, the calling workflow uses this type for the derived variable. "
                    "Use this to ensure proper type inference when workflows are called as subprocesses."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "ID of the workflow to set output for",
                        },
                        "name": {
                            "type": "string",
                            "description": "Name of the output (e.g., 'BMI Result', 'Credit Score', 'Risk Level')",
                        },
                        "type": {
                            "type": "string",
                            "enum": ["string", "int", "float", "bool", "enum", "date"],
                            "description": "Output type - determines derived variable type in calling workflows",
                        },
                        "description": {
                            "type": "string",
                            "description": "Optional description of what this output represents",
                        },
                    },
                    "required": ["workflow_id", "name", "type"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "compile_python",
                "description": (
                    "Generate Python code from the current workflow. "
                    "Returns executable Python source code with typed function parameters, "
                    "if/else statements for decisions, and return statements for outputs. "
                    "Use this when the user asks to export, generate, or compile the workflow to Python."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "include_main": {
                            "type": "boolean",
                            "description": "Whether to include an if __name__ == '__main__' block. Default: false",
                        },
                        "include_docstring": {
                            "type": "boolean",
                            "description": "Whether to include a docstring with parameter descriptions. Default: true",
                        },
                    },
                    "required": [],
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
        "## CRITICAL: Workflow ID-Centric Architecture\n"
        "Every workflow operation requires a workflow_id. The workflow must exist before you can edit it.\n\n"
        "### Creating a New Workflow\n"
        "ALWAYS call create_workflow FIRST when building a new workflow:\n"
        "```\n"
        "create_workflow(name='BMI Calculator', output_type='float')\n"
        "// Returns: {workflow_id: 'wf_abc123', ...}\n"
        "```\n"
        "Then use that workflow_id in ALL subsequent tool calls.\n\n"
        "### Editing an Existing Workflow\n"
        "If the user mentions an existing workflow by name, call list_workflows_in_library to find its ID first.\n\n"
        "## CRITICAL: When to Call Tools\n"
        "ALWAYS call tools immediately when the user uses action verbs:\n"
        "- CREATE NEW WORKFLOW → call create_workflow (FIRST!)\n"
        "- ADD/CREATE (node) → call add_node with workflow_id\n"
        "- DELETE/REMOVE (node) → call delete_node with workflow_id\n"
        "- DELETE/REMOVE (connection/edge) → call delete_connection with workflow_id\n"
        "- DISCONNECT/UNLINK → call delete_connection with workflow_id\n"
        "- MODIFY/CHANGE/UPDATE/RENAME → call modify_node with workflow_id\n"
        "- CONNECT/LINK → call add_connection with workflow_id\n"
        "- WHAT/SHOW/LIST/DESCRIBE → call get_current_workflow with workflow_id\n"
        "- VALIDATE/CHECK/VERIFY → call validate_workflow with workflow_id\n"
        "- RUN/EXECUTE/TEST/TRY → call execute_workflow with workflow_id\n"
        "- VIEW/LIST/SHOW (library/saved workflows) → call list_workflows_in_library\n"
        "- SAVE/KEEP/PUBLISH (workflow) → call save_workflow_to_library with workflow_id\n"
        "- COMPILE/GENERATE/EXPORT (to Python/code) → call compile_python\n\n"
        "## Checking for Existing Workflows\n"
        "WHENEVER the user wants to create a new workflow, ALWAYS call list_workflows_in_library first to check "
        "if a similar workflow already exists. This prevents duplicates and helps users discover what they've already built.\n\n"
        "Examples:\n"
        "- User: 'Create a BMI calculation workflow'\n"
        "  → First call list_workflows_in_library(search_query='BMI') to check\n"
        "  → If none exist, call create_workflow(name='BMI Calculator', output_type='float')\n"
        "  → Then use the returned workflow_id for all subsequent tools\n"
        "- User: 'Show me my saved workflows' → Call list_workflows_in_library()\n"
        "- User: 'Do I have any healthcare workflows?' → Call list_workflows_in_library(domain='Healthcare')\n\n"
        "DO NOT ask for confirmation. DO NOT clarify unless the request is truly ambiguous (e.g., 'add a node' without any description). "
        "If the user says 'add a start node', immediately call add_node with the current workflow_id. "
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
        "- 'Create start → process → end' = 3x add_node + 2x add_connection calls (all with same workflow_id)\n"
        "- 'Add 3 validation nodes' = 3x add_node calls\n"
        "- 'Delete node X and reconnect Y to Z' = delete_node + add_connection\n\n"
        "If the user asks for ONE thing, call ONE tool. Don't overthink it.\n\n"
        "## Working with Node IDs\n"
        "Nodes have IDs like 'node_abc123'. When the user refers to nodes by label:\n"
        "1. Call get_current_workflow(workflow_id) to see all nodes\n"
        "2. Find the node ID by matching the label\n"
        "3. Use that ID in your tool calls\n"
        "NEVER guess node IDs.\n\n"
        "## Output Nodes (Templates & Types)\n"
        "Output nodes ('end' type) support dynamic values and templates:\n"
        "- output_type: 'string', 'int', 'float', 'bool', or 'json'\n"
        "- output_template: Python f-string style template using input variables, e.g. 'Patient BMI is {BMI}'\n"
        "- output_value: Static value if no template is needed\n"
        "You can set these fields in add_node, modify_node, and batch_edit_workflow.\n"
        "Use templates to make outputs more informative based on inputs.\n\n"
        "## When to Use batch_edit_workflow vs Single Tools\n"
        "Most operations should use single tools (add_node, add_connection, etc.).\n\n"
        "Use batch_edit_workflow when you need to REFERENCE newly created nodes within the same operation.\n\n"
        "KEY FEATURE - Temporary IDs:\n"
        "- Single tools generate real IDs immediately (like 'node_abc123') - you don't know the ID beforehand\n"
        "- batch_edit lets you use temporary IDs (like 'temp_start') that get mapped to real IDs automatically\n"
        "- All operations in the batch can reference each other using these temp IDs\n\n"
        "Common scenarios where batch_edit is recommended:\n\n"
        "1. Decision nodes with branches (most common):\n"
        "```\n"
        "// First: add_workflow_variable(workflow_id='wf_abc123', name='Age', type='number') -> returns variable with id 'var_age_int'\n"
        "batch_edit_workflow(\n"
        "  workflow_id='wf_abc123',\n"
        "  operations=[\n"
        "    {\"op\": \"add_node\", \"id\": \"temp_decision\", \"type\": \"decision\", \"label\": \"Check Age\",\n"
        "     \"condition\": {\"input_id\": \"var_age_int\", \"comparator\": \"gte\", \"value\": 18}},\n"
        "    {\"op\": \"add_node\", \"id\": \"temp_true\", \"type\": \"end\", \"label\": \"Adult\", \"x\": 50, \"y\": 200},\n"
        "    {\"op\": \"add_node\", \"id\": \"temp_false\", \"type\": \"end\", \"label\": \"Minor\", \"x\": 150, \"y\": 200},\n"
        "    {\"op\": \"add_connection\", \"from\": \"temp_decision\", \"to\": \"temp_true\", \"label\": \"true\"},\n"
        "    {\"op\": \"add_connection\", \"from\": \"temp_decision\", \"to\": \"temp_false\", \"label\": \"false\"}\n"
        "  ]\n"
        ")\n"
        "```\n\n"
        "CRITICAL: In batch add_connection operations, use 'from' and 'to' fields (NOT 'from_node_id'/'to_node_id').\n\n"
        "## Response Format\n"
        "After tools execute, briefly confirm what happened: 'Added start node', 'Deleted validation node', 'Connected X to Y'.\n"
        "Keep responses SHORT. Don't show raw JSON to the user.\n\n"
        "## Reading Workflow State\n"
        "When the user asks 'what's on the canvas?' or 'what nodes do we have?', call get_current_workflow(workflow_id) and describe the nodes/edges you see.\n\n"
        "## Workflow Variables (CRITICAL)\n"
        "The workflow uses a UNIFIED VARIABLE SYSTEM. There are two types of variables:\n"
        "- Input variables (source='input'): User-provided values, registered with add_workflow_variable\n"
        "- Derived variables (source='subprocess'): Automatically created when subprocess nodes execute\n\n"
        "### Variable ID Format\n"
        "- Input variables: var_{slug}_{type} (e.g., 'var_patient_age_int', 'var_email_string')\n"
        "- Subprocess outputs: var_sub_{slug}_{type} (e.g., 'var_sub_creditscore_float')\n\n"
        "WHENEVER you see a decision node that checks a condition on data, you MUST register that data as a workflow variable:\n"
        "1. Identify what data the decision checks (e.g., 'Patient Age', 'Order Amount', 'Email Valid')\n"
        "2. Call add_workflow_variable(workflow_id, name, type) to register it with appropriate type\n"
        "3. Note the variable ID from the response (e.g., 'var_patient_age_int')\n"
        "4. Then add the decision node with a condition parameter\n\n"
        "Examples:\n"
        "- User: 'Add decision: is patient over 60?'\n"
        "  → Call add_workflow_variable(workflow_id='wf_abc', name='Patient Age', type='number') → returns id='var_patient_age_int'\n"
        "  → Then add_node(workflow_id='wf_abc', type='decision', label='Patient over 60?',\n"
        "      condition={\"input_id\": \"var_patient_age_int\", \"comparator\": \"gt\", \"value\": 60})\n\n"
        "ALWAYS register input variables BEFORE creating nodes that reference them.\n"
        "Use list_workflow_variables(workflow_id) to see what variables already exist AND to get their IDs.\n\n"
        "## Decision Node Conditions (CRITICAL)\n"
        "EVERY decision node MUST have a structured `condition` that defines the logic.\n\n"
        "### Condition Structure\n"
        "A condition is an object with these fields:\n"
        "- `input_id`: ID of the workflow variable to check (e.g., 'var_patient_age_int' or 'var_sub_creditscore_float')\n"
        "- `comparator`: The comparison operator (see table below)\n"
        "- `value`: Value to compare against\n"
        "- `value2`: (Optional) Second value for range comparators\n\n"
        "### Comparators by Variable Type\n"
        "| Variable Type | Valid Comparators |\n"
        "|---------------|-------------------|\n"
        "| int, float    | eq, neq, lt, lte, gt, gte, within_range |\n"
        "| bool          | is_true, is_false |\n"
        "| string        | str_eq, str_neq, str_contains, str_starts_with, str_ends_with |\n"
        "| date          | date_eq, date_before, date_after, date_between |\n"
        "| enum          | enum_eq, enum_neq |\n\n"
        "CRITICAL:\n"
        "- Decision nodes WITHOUT a condition will FAIL at execution time\n"
        "- The input_id MUST match an existing variable's ID (get from list_workflow_variables)\n"
        "- For input variables: var_{slug}_{type}\n"
        "- For subprocess outputs: var_sub_{slug}_{type}\n"
        "- The comparator MUST be valid for the variable's type\n"
        "- For within_range/date_between, you MUST provide both value and value2\n\n"
        "## Subprocess Nodes (Subflows)\n"
        "Use subprocess nodes to call other workflows as reusable components.\n\n"
        "WHEN TO USE SUBPROCESS:\n"
        "- When a workflow has complex sub-logic that exists as a separate workflow\n"
        "- When the user wants to reuse an existing workflow within another\n"
        "- When breaking down large workflows into modular pieces\n\n"
        "REQUIRED FIELDS FOR SUBPROCESS NODES:\n"
        "1. subworkflow_id: The ID of the workflow to call (use list_workflows_in_library to find it)\n"
        "2. input_mapping: Maps parent workflow variable names to subworkflow input names\n"
        "   Example: {\"ApplicantAge\": \"Age\", \"AnnualIncome\": \"Income\"}\n"
        "   This maps parent's 'ApplicantAge' variable to subworkflow's 'Age' input\n"
        "3. output_variable: Name for the output (e.g., 'CreditScore')\n"
        "   This automatically creates a DERIVED VARIABLE with ID 'var_sub_creditscore_float'\n"
        "   that can be used in subsequent decision nodes\n\n"
        "## Setting Workflow Output Type (For Subworkflow Authors)\n"
        "When creating a workflow that will be used as a subprocess, use set_workflow_output to declare "
        "the output with its correct type. This ensures calling workflows get the right type inference.\n\n"
        "```\n"
        "// In the BMI Calculator subworkflow:\n"
        "set_workflow_output(\n"
        "  workflow_id='wf_bmi123',\n"
        "  name='BMI',\n"
        "  type='float',  // BMI is a float value like 24.5\n"
        "  description='Calculated Body Mass Index'\n"
        ")\n"
        "```\n\n"
        "WHY THIS MATTERS:\n"
        "- When another workflow adds a subprocess node calling this workflow\n"
        "- The derived variable type is inferred from the output definition\n"
        "- Without proper output type, the default is 'string' which causes type mismatches\n"
        "- With proper output type (float), the derived variable is var_sub_bmi_float"
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
