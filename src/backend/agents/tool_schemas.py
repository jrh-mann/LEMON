"""Tool schema definitions for the orchestrator.

Contains the tool_descriptions() function that returns the list of
tool schemas in Anthropic function-calling format. These schemas
tell the LLM what tools are available and how to call them.

Extracted from orchestrator_config.py (931 lines) to keep files focused.
"""

from __future__ import annotations

from typing import Any, Dict, List


def tool_descriptions() -> List[Dict[str, Any]]:
    """Return the list of tool schemas for the orchestrator.

    Each schema follows the Anthropic tool-calling format with
    type, function name, description, and parameter definitions.

    Returns:
        List of tool schema dicts ready for the LLM API.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "view_image",
                "description": (
                    "Re-examine an uploaded workflow image. When multiple images are "
                    "uploaded, pass the filename to select a specific one."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Name of the image file to view. If omitted, returns the first image.",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "extract_guidance",
                "description": (
                    "Extract side information (sticky notes, legends, annotations, linked "
                    "guidance panels) from an uploaded workflow image. Makes a separate "
                    "API call and returns structured guidance items. Call this BEFORE "
                    "building the workflow to discover extra context in the image. "
                    "When multiple images are uploaded, pass the filename to select one."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Name of the image file. If omitted, uses the first image.",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "update_plan",
                "description": (
                    "Update the step-by-step plan shown to the user. Call this to outline "
                    "what you see in the image and mark items as done as you build the workflow."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "description": "List of plan items to display.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "text": {
                                        "type": "string",
                                        "description": "Description of this plan step.",
                                    },
                                    "done": {
                                        "type": "boolean",
                                        "description": "Whether this step is completed.",
                                    },
                                },
                                "required": ["text", "done"],
                            },
                        },
                    },
                    "required": ["items"],
                },
            },
        },
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
                            "enum": ["string", "number", "bool", "json"],
                            "description": "Type of value the workflow returns when executed. Use 'number' for all numeric values.",
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
                "name": "create_subworkflow",
                "description": (
                    "Create a subworkflow and build it in the background. Returns a workflow_id "
                    "immediately that you can use as the subworkflow_id in a subprocess node. "
                    "A background orchestrator builds the subworkflow's nodes and connections "
                    "autonomously using your brief. FIRST check list_workflows_in_library to "
                    "see if a suitable workflow already exists before calling this."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name for the subworkflow (e.g., 'BMI Calculator', 'Credit Score Assessment')",
                        },
                        "output_type": {
                            "type": "string",
                            "enum": ["string", "number", "bool", "json"],
                            "description": "Type of value the subworkflow returns",
                        },
                        "brief": {
                            "type": "string",
                            "description": (
                                "Detailed description of the subworkflow's logic. Include: "
                                "what it calculates/decides, step-by-step decision logic, "
                                "all inputs with types, expected output meaning. More detail = better result."
                            ),
                        },
                        "inputs": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "description": "Input variable name",
                                    },
                                    "type": {
                                        "type": "string",
                                        "enum": ["string", "number", "bool", "json"],
                                        "description": "Input variable type",
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": "What this input represents",
                                    },
                                },
                                "required": ["name", "type"],
                            },
                            "description": "Input variables the subworkflow expects",
                        },
                    },
                    "required": ["name", "output_type", "brief", "inputs"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "update_subworkflow",
                "description": (
                    "Update an existing subworkflow by resuming its builder with new instructions. "
                    "The builder retains full context of how the workflow was originally built. "
                    "Returns immediately while the update happens in the background."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "ID of the subworkflow to update",
                        },
                        "instructions": {
                            "type": "string",
                            "description": (
                                "Detailed instructions for what to change. Be specific about "
                                "which nodes to add/modify/remove and what logic to change."
                            ),
                        },
                    },
                    "required": ["workflow_id", "instructions"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ask_question",
                "description": (
                    "Ask the user a clarification question. Use this whenever you are "
                    "UNSURE about any detail — a threshold, label, branch condition, or "
                    "ambiguous text. Provide options when possible so the user can click "
                    "instead of typing. Do NOT guess; ask."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The question to ask the user.",
                        },
                        "options": {
                            "type": "array",
                            "description": "Optional clickable choices (2-4 recommended).",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label": {
                                        "type": "string",
                                        "description": "Display text for the option.",
                                    },
                                    "value": {
                                        "type": "string",
                                        "description": "Value sent back when user clicks this option.",
                                    },
                                },
                                "required": ["label", "value"],
                            },
                        },
                    },
                    "required": ["question"],
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
                            "enum": ["start", "process", "decision", "subprocess", "calculation", "end"],
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
                            "enum": ["string", "number", "bool", "json"],
                            "description": "For 'end' nodes: data type of the output. Use 'number' for all numeric values.",
                        },
                        "output_variable": {
                            "type": "string",
                            "description": (
                                "For 'end' nodes returning number/bool: Name of the variable to return (e.g., 'BMI'). "
                                "Returns the raw value preserving type. Do NOT use output_template for numeric returns. "
                                "For 'subprocess' nodes: Name for the variable that stores the subworkflow's output."
                            ),
                        },
                        "output_template": {
                            "type": "string",
                            "description": "For 'end' nodes returning STRINGS only: Python f-string template (e.g. 'Patient BMI is {BMI}'). Do NOT use for number/bool outputs.",
                        },
                        "output_value": {
                            "type": "string",
                            "description": "For 'end' nodes: Static literal value to return (e.g., 42, true, 'fixed string').",
                        },
                        "condition": {
                            "description": (
                                "REQUIRED for 'decision' nodes. Can be simple or compound.\n"
                                "Simple: {input_id, comparator, value, value2?}\n"
                                "Compound: {operator: 'and'|'or', conditions: [simple, simple, ...]}\n"
                                "Use compound when a decision checks MULTIPLE variables (e.g., 'Symptoms AND A1c > 58').\n"
                                "Compound must have >= 2 sub-conditions. No nesting."
                            ),
                            "oneOf": [
                                {
                                    "type": "object",
                                    "description": "Simple condition",
                                    "properties": {
                                        "input_id": {"type": "string", "description": "ID of the workflow variable to check"},
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
                                    "required": ["input_id", "comparator"]
                                },
                                {
                                    "type": "object",
                                    "description": "Compound condition (AND/OR)",
                                    "properties": {
                                        "operator": {"type": "string", "enum": ["and", "or"]},
                                        "conditions": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "input_id": {"type": "string"},
                                                    "comparator": {"type": "string"},
                                                    "value": {},
                                                    "value2": {}
                                                },
                                                "required": ["input_id", "comparator"]
                                            },
                                            "minItems": 2
                                        }
                                    },
                                    "required": ["operator", "conditions"]
                                }
                            ]
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
                        "calculation": {
                            "type": "object",
                            "description": (
                                "For 'calculation' nodes: Defines a mathematical operation on variables. "
                                "The result is stored in an output variable that can be used by subsequent nodes."
                            ),
                            "properties": {
                                "output": {
                                    "type": "object",
                                    "description": "Output variable definition",
                                    "properties": {
                                        "name": {"type": "string", "description": "Name for the calculated result. Must be alphanumeric with underscores only, no spaces (e.g., 'BMI', 'Total_Score', 'DTI_Ratio')"},
                                        "description": {"type": "string", "description": "Description of what this value represents"},
                                    },
                                    "required": ["name"],
                                },
                                "operator": {
                                    "type": "string",
                                    "description": "Mathematical operator to apply. See system prompt for full list.",
                                    "enum": [
                                        "add", "subtract", "multiply", "divide", "floor_divide", "modulo", "power",
                                        "negate", "abs", "sqrt", "square", "cube", "reciprocal",
                                        "floor", "ceil", "round", "sign",
                                        "ln", "log10", "log", "exp",
                                        "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
                                        "degrees", "radians",
                                        "min", "max", "sum", "average", "hypot",
                                        "geometric_mean", "harmonic_mean", "variance", "std_dev", "range"
                                    ],
                                },
                                "operands": {
                                    "type": "array",
                                    "description": "List of operands for the operator",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "kind": {
                                                "type": "string",
                                                "enum": ["variable", "literal"],
                                                "description": "'variable' to reference a workflow variable, 'literal' for a constant number",
                                            },
                                            "ref": {
                                                "type": "string",
                                                "description": "For kind='variable': variable ID (e.g., 'var_weight_number')",
                                            },
                                            "value": {
                                                "type": "number",
                                                "description": "For kind='literal': the constant numeric value",
                                            },
                                        },
                                        "required": ["kind"],
                                    },
                                },
                            },
                            "required": ["output", "operator", "operands"],
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
                    "For DECISION nodes: You can update the condition.\n"
                    "For CALCULATION nodes: You can update the calculation definition."
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
                            "enum": ["start", "process", "decision", "subprocess", "calculation", "end"],
                            "description": "New node type",
                        },
                        "x": {"type": "number", "description": "New X coordinate"},
                        "y": {"type": "number", "description": "New Y coordinate"},
                        "output_type": {
                            "type": "string",
                            "enum": ["string", "number", "bool", "json"],
                            "description": "For 'end' nodes: data type of the output. Use 'number' for all numeric values.",
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
                            "description": (
                                "For 'decision' nodes: Simple or compound condition. "
                                "See add_node for full schema details."
                            ),
                            "oneOf": [
                                {
                                    "type": "object",
                                    "properties": {
                                        "input_id": {"type": "string"},
                                        "comparator": {"type": "string"},
                                        "value": {},
                                        "value2": {}
                                    },
                                    "required": ["input_id", "comparator"]
                                },
                                {
                                    "type": "object",
                                    "properties": {
                                        "operator": {"type": "string", "enum": ["and", "or"]},
                                        "conditions": {"type": "array", "minItems": 2}
                                    },
                                    "required": ["operator", "conditions"]
                                }
                            ]
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
                            "description": (
                                "For 'end' nodes returning number/bool: Name of the variable to return (e.g., 'BMI'). "
                                "Returns the raw value preserving type. Do NOT use output_template for numeric returns. "
                                "For 'subprocess' nodes: Name for the variable that stores the subworkflow's output."
                            ),
                        },
                        "calculation": {
                            "type": "object",
                            "description": "For 'calculation' nodes: Updated calculation definition. See add_node for schema.",
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
                                "add_node: {op, type, label, id (temp ID for referencing), x, y, condition?, output_type?, output_template?, output_value?, subworkflow_id?, input_mapping?, output_variable?, calculation?}\n"
                                "modify_node: {op, node_id, label?, type?, x?, y?, condition?, output_type?, output_template?, output_value?, subworkflow_id?, input_mapping?, output_variable?, calculation?}\n"
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
                                    "type": {"type": "string", "enum": ["start", "process", "decision", "subprocess", "calculation", "end"]},
                                    "label": {"type": "string"},
                                    "x": {"type": "number"},
                                    "y": {"type": "number"},
                                    "condition": {
                                        "description": "For decision nodes: simple {input_id, comparator, value} or compound {operator, conditions: [...]}",
                                    },
                                    "output_type": {"type": "string", "enum": ["string", "number", "bool", "json"]},
                                    "output_template": {"type": "string"},
                                    "output_value": {"type": "string"},
                                    "subworkflow_id": {"type": "string", "description": "For subprocess: workflow ID to call"},
                                    "input_mapping": {"type": "object", "description": "For subprocess: parent->subworkflow input mapping"},
                                    "output_variable": {"type": "string", "description": "For end nodes: variable name to return raw value (number/bool). For subprocess: name for output variable."},
                                    "calculation": {"type": "object", "description": "For calculation nodes: {output, operator, operands} - see add_node for full schema"},
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
                    "Modify an existing user-input workflow variable's properties (type, name, description, range, enum values). "
                    "Requires workflow_id. "
                    "ONLY works on user-input variables (source='input'). "
                    "Derived variables (from calculation or subprocess nodes) CANNOT be modified — "
                    "modify the producing node instead (e.g. change the calc output name or subprocess output_variable). "
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
                            "enum": ["string", "number", "bool", "enum", "date"],
                            "description": "Output type - determines derived variable type in calling workflows. Use 'number' for all numeric values.",
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
                "name": "highlight_node",
                "description": (
                    "Highlight a node on the canvas to draw the user's attention to it. "
                    "The node pulses briefly. Use this when referencing a specific node "
                    "in conversation so the user can see which one you mean."
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
                            "description": "ID of the node to highlight",
                        },
                    },
                    "required": ["node_id"],
                },
            },
        },
    ]
