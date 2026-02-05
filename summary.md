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
7. **Calculation Nodes**: Mathematical operations with 40+ operators (arithmetic, trigonometric, statistical)
8. **Python Code Generation**: Export workflows to executable Python functions
9. **User Authentication**: Session-based auth with SQLite storage

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
│   │   │   ├── orchestrator_config.py  # System prompt + tool schemas (1123 lines)
│   │   │   ├── orchestrator_factory.py # Factory function
│   │   │   └── subagent.py         # Image analysis agent
│   │   ├── api/                    # HTTP + WebSocket server
│   │   │   ├── app.py              # Flask app factory
│   │   │   ├── routes.py           # REST endpoints
│   │   │   ├── socket_handlers.py  # Socket.IO event registration
│   │   │   ├── socket_chat.py      # Chat message processing
│   │   │   ├── socket_execution.py # Workflow execution events
│   │   │   ├── auth.py             # Authentication middleware
│   │   │   ├── conversations.py    # Session state management
│   │   │   └── tool_summaries.py   # Tool call aggregation for UI
│   │   ├── tools/                  # LLM tool implementations (20 tools)
│   │   │   ├── workflow_edit/      # Node/edge manipulation tools
│   │   │   ├── workflow_input/     # Variable management tools
│   │   │   ├── workflow_output/    # Output declaration tools
│   │   │   ├── workflow_analysis/  # Image analysis tools
│   │   │   ├── workflow_library/   # Saved workflow tools (list, create, save)
│   │   │   ├── validate_workflow.py
│   │   │   ├── execute_workflow.py # Run workflow by ID
│   │   │   └── compile_python.py   # Export to Python code
│   │   ├── validation/             # Workflow validator
│   │   ├── execution/              # Workflow interpreter
│   │   │   ├── interpreter.py      # Tree traversal engine
│   │   │   ├── evaluator.py        # Condition evaluation
│   │   │   ├── operators.py        # Mathematical operators (40+)
│   │   │   ├── python_compiler.py  # Python code generator (865 lines)
│   │   │   ├── parser.py           # Workflow parsing
│   │   │   └── types.py            # Block types
│   │   ├── llm/                    # LLM client abstraction
│   │   ├── mcp_bridge/             # Model Context Protocol
│   │   ├── storage/                # SQLite persistence
│   │   └── utils/                  # Utilities (flowchart, tokens, uploads, etc.)
│   └── frontend/                   # React + TypeScript
│       └── src/
│           ├── components/         # UI components
│           │   ├── Canvas.tsx      # SVG workflow editor (~54KB)
│           │   ├── RightSidebar.tsx # Variables & outputs panel (~60KB)
│           │   ├── Modals.tsx      # Dialogs (save, execute, etc.)
│           │   ├── Chat.tsx        # AI chat interface
│           │   ├── Header.tsx      # Top navigation
│           │   ├── Palette.tsx     # Node palette
│           │   ├── WorkflowBrowser.tsx # Library browser
│           │   └── ...
│           ├── stores/             # Zustand state management
│           │   ├── workflowStore.ts  # Workflow state (~27KB)
│           │   ├── chatStore.ts      # Chat state
│           │   ├── uiStore.ts        # UI state
│           │   └── validationStore.ts # Validation state
│           ├── api/                # Backend communication
│           │   ├── socket.ts       # Socket.IO client
│           │   └── ...
│           └── utils/canvas/       # Canvas utilities
└── tests/                          # pytest test suites
    ├── conftest.py                 # Test fixtures
    ├── execution/                  # Execution engine tests (12 files)
    └── [24 test files]             # Tool, validation, integration tests
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

The orchestrator has access to **20 tools** organized in 7 categories:

### Workflow Creation & Library
| Tool | Purpose |
|------|---------|
| `create_workflow` | **MUST BE CALLED FIRST** - Create new workflow in DB, returns workflow_id |
| `list_workflows_in_library` | Search saved workflows + current canvas workflow |
| `save_workflow_to_library` | Save workflow to user's permanent library |

### Workflow Editing
| Tool | Purpose |
|------|---------|
| `get_current_workflow` | Read workflow state (nodes, edges, variables) by ID |
| `add_node` | Add a single node (start, process, decision, subprocess, calculation, end) |
| `modify_node` | Update node properties (label, type, position, condition, calculation) |
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

### Execution & Export
| Tool | Purpose |
|------|---------|
| `execute_workflow` | Run a workflow by ID with input values |
| `compile_python` | Generate executable Python code from workflow |

### Tool Aliases (Backwards Compatibility)
The following aliases exist for renamed tools:
- `add_workflow_input` → `add_workflow_variable`
- `modify_workflow_input` → `modify_workflow_variable`
- `remove_workflow_input` → `remove_workflow_variable`

---

## Node Types

| Type | Shape | Purpose |
|------|-------|---------|
| `start` | Rounded rectangle (teal) | Entry point (exactly one required) |
| `process` | Rectangle (neutral) | Processing step |
| `decision` | Diamond (amber) | Branch based on condition |
| `calculation` | Rectangle with formula icon | Mathematical operation on variables |
| `subprocess` | Double-bordered rect (rose) | Call another workflow |
| `end` | Rounded rectangle (green) | Output/termination |

### Calculation Nodes

Calculation nodes perform mathematical operations and create derived variables:

**Supported Operators (40+):**
| Category | Operators |
|----------|-----------|
| Arithmetic | add, subtract, multiply, divide, floor_divide, modulo, power |
| Unary | negate, abs, sqrt, square, cube, reciprocal |
| Rounding | floor, ceil, round, sign |
| Logarithmic | ln, log10, log, exp |
| Trigonometric | sin, cos, tan, asin, acos, atan, atan2, degrees, radians |
| Statistical | min, max, sum, average, hypot, geometric_mean, harmonic_mean, variance, std_dev, range |

**Calculation Structure:**
```json
{
  "output": {"name": "BMI", "description": "Body Mass Index"},
  "operator": "divide",
  "operands": [
    {"kind": "variable", "ref": "var_weight_number"},
    {"kind": "literal", "value": 2}
  ]
}
```

Output variables are automatically registered with ID format: `var_calc_{slug}_number`

### Subprocess Nodes

Subprocess nodes call other workflows:
- `subworkflow_id`: ID of workflow to execute
- `input_mapping`: Maps parent variables to subflow inputs
- `output_variable`: Name for derived variable holding subflow output

The output variable is automatically registered with the inferred type from the subworkflow's declared output.

### End Node Outputs

End nodes support multiple output modes:
- `output_type`: 'string', 'number', 'bool', or 'json'
- `output_variable`: Direct variable reference (preserves type - **preferred for number/bool**)
- `output_value`: Static literal value
- `output_template`: Python f-string template (**only for string outputs**)

**Critical:** Use `output_variable` for numeric/boolean outputs. `output_template` converts to strings.

---

## Unified Variable System

LEMON uses a unified variable system where all data flows through typed variables:

### Variable Types
- **Input variables** (`source='input'`): User-provided values at execution time
- **Derived variables** (`source='subprocess'`): Created when subprocess nodes execute
- **Calculated variables** (`source='calculated'`): Created by calculation nodes

### Variable ID Format
- Input: `var_{slug}_{type}` (e.g., `var_patient_age_number`)
- Subprocess: `var_sub_{slug}_{type}` (e.g., `var_sub_bmi_number`)
- Calculated: `var_calc_{slug}_number` (e.g., `var_calc_bmi_number`)

### Supported Types
| Type | Comparators |
|------|-------------|
| `int`, `float`, `number` | eq, neq, lt, lte, gt, gte, within_range |
| `bool` | is_true, is_false |
| `string` | str_eq, str_neq, str_contains, str_starts_with, str_ends_with |
| `date` | date_eq, date_before, date_after, date_between |
| `enum` | enum_eq, enum_neq |

### Decision Node Conditions

Decision nodes use structured conditions:
```json
{
  "input_id": "var_age_number",
  "comparator": "gte",
  "value": 18
}
```

The validator ensures:
- `input_id` references a registered variable
- `comparator` is valid for the variable's type
- Both `true` and `false` branches exist

---

## Python Code Generation

The `PythonCodeGenerator` (865 lines) compiles workflow trees to executable Python:

**Features:**
- Typed function parameters from workflow variables
- if/else statements for decision nodes
- Return statements for end nodes (preserving output type)
- Variable name resolution with conflict handling
- Warning generation for subprocess nodes (not supported in standalone code)
- Optional docstrings and `if __name__ == "__main__"` blocks

**Example Output:**
```python
def loan_approval(age: float, income: float) -> str:
    """Loan approval workflow.
    
    Args:
        age: Applicant age
        income: Annual income
    """
    if age >= 18:
        if income >= 50000:
            return "Approved"
        else:
            return "Conditional Approval"
    else:
        return "Rejected: Underage"
```

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
4. Traverses nodes, evaluates conditions, runs calculations
   ↓
5. Emits execution_step events (node highlighting)
   ↓
6. Reaches end node, evaluates output
   ↓
7. Returns ExecutionResult with output + path
```

### Workflow ID-Centric Architecture
All workflow operations require a `workflow_id`. The workflow must exist in the database before editing:
1. Call `create_workflow` first → returns workflow_id
2. Use that workflow_id in ALL subsequent tool calls
3. For existing workflows, use `list_workflows_in_library` to find the ID

---

## Validation Rules

The `WorkflowValidator` enforces (strict mode for saves/execution):

**Always Enforced:**
- Nodes have required fields (id, type, label, x, y)
- Valid node types only (start, process, decision, calculation, subprocess, end)
- Edges reference existing nodes
- No duplicate IDs
- No self-loops
- No cycles (DAG requirement)
- At most one start node
- Decision conditions have valid `input_id` and `comparator`
- Calculation nodes have valid operator and operands

**Strict Mode Only:**
- At least one start node
- Decision nodes have 2+ branches with true/false labels
- Start nodes have outgoing edges
- End nodes have no outgoing edges
- All nodes reachable from start
- Process/subprocess/calculation nodes have outgoing connections

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
  "output_type": "number",
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

### Tool Summary Tracking
- `ToolSummaryTracker` in `api/tool_summaries.py` aggregates tool calls
- Generates user-friendly status messages (e.g., "Added a workflow node x3")
- Tracks both successes and failures

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

## Recent Changes (2026-02-05)

### Dev Tools & Experience
1. **Dev Tools Sidebar**: Moved Developer Tools to a dedicated "Dev Mode" in the Left Sidebar, replacing the Palette when active.
2. **Tool Inspector**: New "Tools" tab in Dev Tools to browse and execute MCP tools directly from the UI.
3. **Execution Logging**: 
    - Enhanced indentation for nested subflows (client-side stack tracking).
    - Visual separation of "Entering Subflow" headers and indented content.
    - Direct logging of Start (inputs) and End (outputs) nodes.
4. **UI Refinements**: Failed tool calls in chat are now visually distinct.
5. **Variable Display**: Separated "Inputs" from "Expected Variables" (Calculated/Derived) in the sidebar with source tags.
6. **Execution Safety**: Execution modal now restricts manual input to only variables with `source='input'`.
7. **Calculation Node Persistence**: Fixed `batch_edit` tool to correctly handle and preserve calculation node metadata.
8. **Cross-Workflow Safety**: Fixed socket event leakage where updates from background workflows would appear on unrelated tabs.

## Recent Changes (2026-02-04)

### New Features
1. **Calculation Nodes**: New node type for mathematical operations with 40+ operators (arithmetic, trigonometric, statistical)
2. **Python Code Generation**: `compile_python` tool and `PythonCodeGenerator` (865 lines) to export workflows as executable Python functions
3. **Execute Workflow Tool**: LLM can now run workflows by ID with `execute_workflow` tool
4. **Create Workflow Tool**: Explicit workflow creation with `create_workflow` - must be called before any editing
5. **Tool Summary Tracking**: `ToolSummaryTracker` aggregates tool call results for user-friendly status messages

### Architecture Changes
1. **Workflow ID-Centric Design**: All tools now require `workflow_id` parameter
2. **End Node Output Types**: Support for `output_type`, `output_variable`, `output_value` for type-preserving outputs
3. **Validation Store**: New `validationStore.ts` in frontend for validation state management
4. **Operator Module**: `operators.py` with 40+ mathematical operators for calculation nodes

### Previous Changes (2026-01-29)
1. **Variable Sync Fix**: Frontend analysis (variables) now properly syncs to backend via chat messages and `sync_workflow` events
2. **Save Validation Fix**: Save endpoint now uses `variables` key (not `inputs`) when calling validator
3. **Subprocess Output Variables**: Validator now recognizes `output_variable` from subprocess nodes as valid variables for end node templates
