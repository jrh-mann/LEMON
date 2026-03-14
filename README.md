# LEMON

A conversational AI system for building and executing clinical decision workflows. Describe a workflow in natural language or upload a flowchart image, and an LLM orchestrator builds a structured, executable decision tree on a visual canvas.

## Features

- **Natural language workflow building** — describe what you want, the LLM builds it node-by-node using tool calls
- **Image-to-workflow** — upload a flowchart photo or PDF and the system reconstructs it as an editable workflow
- **Visual canvas editor** — interactive SVG canvas with drag-and-drop, connection drawing, and real-time updates as the LLM works
- **Six node types** — start, process, decision, calculation, subprocess, and end nodes with conditional branching and expression evaluation
- **Subworkflows** — extract reusable sub-procedures that can be called from parent workflows
- **Stepped execution** — run workflows with test inputs and watch execution step through each node with live highlighting
- **Workflow library** — save, browse, and reuse workflows across sessions
- **Streaming** — SSE-based real-time streaming of LLM responses, tool calls, and canvas updates

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19, TypeScript, Zustand, Vite |
| Backend | FastAPI, Uvicorn, Python 3.10+ |
| LLM | Anthropic Claude (tool use, streaming) |
| Database | SQLite |
| Streaming | Server-Sent Events (SSE) |
| Auth | Session-based with PBKDF2 password hashing |

## Setup

### Prerequisites

- Python 3.10+
- Node.js 18+
- [uv](https://github.com/astral-sh/uv) for Python dependency management
- Anthropic API key

### Install

```bash
uv sync
cd src/frontend && npm install
```

### Configure

Copy `.env.example` to `.env` and fill in your keys:

```
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-opus-4-6
```

## Running

```bash
./scripts/dev.sh            # start backend + frontend
./scripts/dev.sh restart    # kill and restart
./scripts/dev.sh stop       # stop all
```

- **Backend:** http://localhost:5001
- **Frontend:** http://localhost:5173
- **Logs:** `/tmp/lemon-backend.log`, `/tmp/lemon-frontend.log`

Or start individually:

```bash
python run_api.py                        # backend
cd src/frontend && npx vite --host       # frontend
```

## Testing

```bash
# Full backend test suite (~1200 tests)
uv run python -m pytest tests/

# Frontend unit tests
cd src/frontend && npm test

# Frontend E2E tests
cd src/frontend && npm run test:e2e

# Type check
cd src/frontend && npx tsc --noEmit
```

## License

MIT — see [LICENSE](LICENSE).
