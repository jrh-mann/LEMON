# LEMON Project - Technical Summary

## Overview

**LEMON** (Learning Encoded Mindmaps and Operational Notes) is an AI-assisted workflow builder that enables users to create, edit, validate, and execute decision flowcharts through both visual manipulation and natural language conversation.

### Core Capabilities

1. **Visual Workflow Building**: SVG-based canvas with drag-and-drop node creation
2. **AI-Powered Assistance**: Claude Sonnet 4 orchestrator for natural language workflow manipulation
3. **Image-to-Workflow**: Upload hand-drawn flowcharts and convert to structured digital workflows
4. **Workflow Execution**: Execute workflows with typed inputs, traversing decision trees to produce outputs
5. **Validation**: Comprehensive structural validation (cycles, reachability, branches, conditions)
6. **Subprocess Support**: Hierarchical workflows with subflow execution and derived variables
7. **User Authentication**: Session-based auth with SQLite storage

### Primary Use Cases

- Clinical/medical decision support (BMI, cholesterol, medication decisions)
- Business process automation
- Any decision tree or flowchart-based logic

---

## Architecture

```
LEMON/
├── src/
│   ├── backend/                    # Python Flask + Socket.IO
│   │   ├── agents/                 # LLM orchestrator
│   │   │   ├── orchestrator.py     # Core agent logic
│   │   │   ├── orchestrator_config.py  # System prompt + tool schemas
│   │   │   ├── orchestrator_factory.py # Factory function
│   │   │   └── subagent.py         # Image analysis agent
│   │   ├── api/                    # HTTP + WebSocket server
│   │   │   ├── app.py              # Flask app factory
│   │   │   ├── routes.py           # REST endpoints
│   │   │   ├── socket_handlers.py  # Socket.IO event registration
│   │   │   ├── socket_chat.py      # Chat message processing
│   │   │   ├── socket_execution.py # Workflow execution events
│   │   │   ├── auth.py             # Authentication middleware
│   │   │   └── conversations.py    # Session state management
│   │   ├── tools/                  # LLM tool implementations (15 tools)
│   │   │   ├── workflow_edit/      # Node/edge manipulation tools
│   │   │   ├── workflow_input/     # Variable management tools
│   │   │   ├── workflow_output/    # Output declaration tools
│   │   │   ├── workflow_analysis/  # Image analysis tools
│   │   │   ├── workflow_library/   # Saved workflow tools
│   │   │   └── validate_workflow.py
│   │   ├── validation/             # Workflow validator
│   │   ├── execution/              # Workflow interpreter
│   │   │   ├── interpreter.py      # Tree traversal engine
│   │   │   ├── evaluator.py        # Condition evaluation
│   │   │   ├── parser.py           # Workflow parsing
│   │   │   └── types.py            # Block types
│   │   ├── llm/                    # LLM client abstraction
│   │   ├── mcp/                    # Model Context Protocol
│   │   └── storage/                # SQLite persistence
│   └── frontend/                   # React + TypeScript
│       └── src/
│           ├── components/         # UI components
│           │   ├── Canvas.tsx      # SVG workflow editor (1536 lines)
│           │   ├── Chat.tsx        # AI chat interface
│           │   ├── Modals.tsx      # Dialogs (save, execute, etc.)
│           │   └── ...
│           ├── stores/             # Zustand state management
│           │   ├── workflowStore.ts
│           │   ├── chatStore.ts
│           │   └── uiStore.ts
│           ├── api/                # Backend communication
│           │   ├── socket.ts       # Socket.IO client
│           │   └── ...
│           └── utils/canvas/       # Canvas utilities
└── tests/                          # pytest test suites (439 tests)
```

### Technology Stack

**Backend:**
- Python 3.12+
- Flask + python-socketio (real-time communication)
- Anthropic Claude API (claude-sonnet-4-20250514)
- SQLite (auth + workflow storage)
- MCP (Model Context Protocol) for tool interoperability

**Frontend:**
- React 19 + TypeScript
- Vite bundler
- Zustand state management
- Socket.IO client
- SVG-based canvas rendering

---

## LLM Tools

The orchestrator has access to 15 tools organized in 6 categories:

### Workflow Editing
| Tool | Purpose |
|------|---------|
| `get_current_workflow` | Read current canvas state (nodes, edges, variables) |
| `add_node` | Add a single node (start, process, decision, subprocess, end) |
| `modify_node` | Update node properties (label, type, position, condition) |
| `delete_node` | Remove node and connected edges |
| `add_connection` | Create edge between nodes |
| `delete_connection` | Remove edge |
| `batch_edit_workflow` | Atomic multi-operation with temp ID support |

### Variable Management
| Tool | Purpose |
|------|---------|
| `add_workflow_variable` | Register user-input variable (string/number/boolean/enum) |
| `list_workflow_variables` | View all variables (inputs + derived) |
| `modify_workflow_variable` | Change variable type, name, constraints |
| `remove_workflow_variable` | Delete variable (with force option for cascade) |
| `set_workflow_output` | Declare workflow output type (for subprocess inference) |

### Analysis & Validation
| Tool | Purpose |
|------|---------|
| `analyze_workflow` | Extract workflow from uploaded image |
| `publish_latest_analysis` | Render analyzed workflow to canvas |
| `validate_workflow` | Check structural correctness |
| `list_workflows_in_library` | Search saved workflows |

### Tool Aliases (Backwards Compatibility)
The following aliases exist for renamed tools:
- `add_workflow_input` → `add_workflow_variable`
- `modify_workflow_input` → `modify_workflow_variable`
- `remove_workflow_input` → `remove_workflow_variable`

---

## Unified Variable System

LEMON uses a unified variable system where all data flows through typed variables:

### Variable Types
- **Input variables** (`source='input'`): User-provided values at execution time
- **Derived variables** (`source='subprocess'`): Created when subprocess nodes execute

### Variable ID Format
- Input: `var_{slug}_{type}` (e.g., `var_patient_age_int`)
- Subprocess: `var_sub_{slug}_{type}` (e.g., `var_sub_bmi_float`)

### Supported Types
| Type | Comparators |
|------|-------------|
| `int`, `float` | eq, neq, lt, lte, gt, gte, within_range |
| `bool` | is_true, is_false |
| `string` | str_eq, str_neq, str_contains, str_starts_with, str_ends_with |
| `date` | date_eq, date_before, date_after, date_between |
| `enum` | enum_eq, enum_neq |

### Decision Node Conditions

Decision nodes use structured conditions:
```json
{
  "input_id": "var_age_int",
  "comparator": "gte",
  "value": 18
}
```

The validator ensures:
- `input_id` references a registered variable
- `comparator` is valid for the variable's type
- Both `true` and `false` branches exist

---

## Node Types

| Type | Shape | Purpose |
|------|-------|---------|
| `start` | Rounded rectangle (teal) | Entry point (exactly one required) |
| `process` | Rectangle (neutral) | Processing step |
| `decision` | Diamond (amber) | Branch based on condition |
| `subprocess` | Double-bordered rect (rose) | Call another workflow |
| `end` | Rounded rectangle (green) | Output/termination |

### Subprocess Nodes

Subprocess nodes call other workflows:
- `subworkflow_id`: ID of workflow to execute
- `input_mapping`: Maps parent variables to subflow inputs
- `output_variable`: Name for derived variable holding subflow output

The output variable is automatically registered with the inferred type from the subworkflow's declared output.

---

## Data Flow

### Chat Message Flow
```
1. User types message
   ↓
2. Frontend: socket.emit('chat', {message, workflow, analysis})
   ↓
3. Backend: SocketChatTask receives, syncs state to conversation
   ↓
4. Orchestrator.respond() with streaming
   ↓
5. Claude decides tool calls → Tools execute → State updates
   ↓
6. Socket events: workflow_update, analysis_updated
   ↓
7. Frontend applies changes to canvas
   ↓
8. Claude generates text response
   ↓
9. Frontend displays streamed response
```

### Workflow Execution Flow
```
1. User provides inputs via Execute modal
   ↓
2. socket.emit('execute_workflow', {workflow, inputs})
   ↓
3. Backend: TreeInterpreter validates inputs
   ↓
4. Traverses nodes, evaluates conditions
   ↓
5. Emits execution_step events (node highlighting)
   ↓
6. Reaches end node, evaluates output template
   ↓
7. Returns ExecutionResult with output + path
```

---

## Validation Rules

The `WorkflowValidator` enforces (strict mode for saves/execution):

**Always Enforced:**
- Nodes have required fields (id, type, label, x, y)
- Valid node types only
- Edges reference existing nodes
- No duplicate IDs
- No self-loops
- No cycles (DAG requirement)
- At most one start node
- Decision conditions have valid `input_id` and `comparator`

**Strict Mode Only:**
- At least one start node
- Decision nodes have 2+ branches with true/false labels
- Start nodes have outgoing edges
- End nodes have no outgoing edges
- All nodes reachable from start
- Process/subprocess nodes have outgoing connections

---

## Socket Events

### Client → Server
| Event | Purpose |
|-------|---------|
| `chat` | Send message with workflow + analysis |
| `sync_workflow` | Explicit workflow sync (uploads, library loads) |
| `cancel_task` | Cancel in-flight operation |
| `execute_workflow` | Start workflow execution |
| `pause_execution` | Pause running execution |
| `resume_execution` | Resume paused execution |
| `stop_execution` | Stop execution |

### Server → Client
| Event | Purpose |
|-------|---------|
| `chat_progress` | Processing status updates |
| `chat_stream` | Streaming response chunks |
| `chat_response` | Final response with tool calls |
| `chat_cancelled` | Operation cancelled |
| `workflow_update` | Single node/edge change |
| `workflow_modified` | Full workflow replacement |
| `analysis_updated` | Variables/outputs changed |
| `execution_started` | Execution began |
| `execution_step` | Node being executed |
| `execution_complete` | Execution finished |
| `agent_error` | Error occurred |

---

## Storage

### SQLite Databases (`.lemon/`)
- `auth.sqlite`: User accounts and sessions
- `workflows.sqlite`: Saved workflows

### Workflow Schema
```json
{
  "id": "wf_abc123",
  "name": "BMI Calculator",
  "description": "...",
  "domain": "Healthcare",
  "tags": ["medical", "bmi"],
  "nodes": [...],
  "edges": [...],
  "inputs": [...],  // Variables stored under 'inputs' key (see note below)
  "outputs": [...],
  "tree": {...},    // Hierarchical structure
  "doubts": [...]   // Analysis ambiguities
}
```

**Note on Variable Storage:** The database schema uses `inputs` column for historical reasons, but the API layer exposes variables under the `variables` key. The orchestrator and conversation classes handle this translation transparently.

---

## Key Implementation Details

### Coordinate Systems
- **Backend**: Top-left coordinates (x, y = top-left corner)
- **Frontend**: Center coordinates (x, y = center of node)
- Transformation in `utils/canvas/transform.ts`

### State Synchronization
- Chat messages include full workflow + analysis atomically
- Prevents race conditions between canvas edits and chat
- Frontend is source of truth for visual state
- Backend orchestrator syncs before tool execution

### Cancellation Support
- Tasks have unique IDs
- `CancellationError` propagates through tool chain
- Streaming stops gracefully on cancel
- Partial content preserved in chat

### Token Usage Tracking
- All Claude API calls logged to `.lemon/tokens_usage.json`
- Per-session and cumulative totals
- Includes cache hit/miss metrics

---

## Backwards Compatibility Patterns

Despite the project's "no backwards compatibility" policy (see CLAUDE.md), certain intentional exceptions exist for database and API stability:

### Intentional Exceptions

1. **Database column naming**: Workflows store variables under `inputs` column. The API layer translates to/from `variables` key.

2. **Tool aliases**: Renamed tools maintain aliases (`add_workflow_input` → `add_workflow_variable`) to avoid breaking LLM tool calls.

3. **Interpreter flexibility**: Accepts both `variables` and `inputs` keys in workflow payloads.

4. **Legacy variable ID format**: Supports both `var_age_int` (new) and `input_age_int` (legacy) formats.

5. **API route flexibility**: Save/update endpoints accept both `variables` and `inputs` in request payload.

### Migration Helpers

The `ensure_workflow_analysis()` helper in `tools/workflow_input/helpers.py` automatically migrates legacy `inputs` data to `variables` format when encountered.

---

## Recent Changes (2026-01-29)

1. **Variable Sync Fix**: Frontend analysis (variables) now properly syncs to backend via chat messages and `sync_workflow` events

2. **Save Validation Fix**: Save endpoint now uses `variables` key (not `inputs`) when calling validator

3. **Subprocess Output Variables**: Validator now recognizes `output_variable` from subprocess nodes as valid variables for end node templates

All 439 tests passing.
