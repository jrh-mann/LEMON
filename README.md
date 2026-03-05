## LEMON

LEMON is a full-stack application for building and executing **clinical decision workflows** through a conversational AI interface. Users describe workflows in natural language or upload flowchart images, and an LLM orchestrator builds structured, executable decision trees with a visual canvas editor.

### Requirements

- Python 3.10+
- Node.js 18+
- [`uv`](https://github.com/astral-sh/uv) for Python dependency management
- Anthropic API key

### Setup

1) Create a `.env` in the repo root:

```
ANTHROPIC_API_KEY=...
E2B_API_KEY=...          # optional — sandbox execution
```

2) Install dependencies:

```bash
uv sync
cd src/frontend && npm install
```

### Running

Start all servers (backend, MCP, frontend) with one command:

```bash
./scripts/dev.sh
```

- **Backend API:** http://localhost:5001
- **MCP Server:** http://localhost:8000
- **Frontend:** http://localhost:5173

Or start individually:

```bash
python run_api.py      # backend
python run_mcp.py      # MCP server
cd src/frontend && npx vite --host   # frontend
```

### Repo layout

```
LEMON/
├── src/
│   ├── backend/
│   │   ├── agents/        # LLM orchestrator and config
│   │   ├── api/           # FastAPI routes, WebSocket handlers
│   │   ├── execution/     # Workflow interpreter and evaluator
│   │   ├── llm/           # Anthropic API wrapper
│   │   ├── mcp/           # MCP server bridge
│   │   ├── storage/       # SQLite persistence
│   │   ├── tools/         # LLM tool implementations
│   │   ├── utils/         # Logging, validation helpers
│   │   └── validation/    # Workflow validation rules
│   └── frontend/          # React + TypeScript + Vite
├── tests/
│   ├── validation/        # Input/schema validation tests
│   ├── tools/             # Tool unit tests
│   ├── integration/       # Cross-component tests
│   ├── workflow/          # Workflow structure/logic tests
│   ├── features/          # Feature-specific and bugfix tests
│   ├── execution/         # Execution engine tests
│   └── live/              # Live integration scripts
├── fixtures/              # Test images, annotations, ground truth
├── docs/                  # Technical debt, known issues, notes
├── scripts/               # Dev scripts (dev.sh, etc.)
├── evals/                 # Evaluation framework and scoring
├── run_api.py             # Backend entry point
├── run_mcp.py             # MCP server entry point
└── pyproject.toml         # Project config and dependencies
```

### Testing

```bash
uv run python -m pytest tests/
```

### Development

```bash
./scripts/dev.sh restart   # restart all servers
./scripts/dev.sh stop      # stop all servers
```
