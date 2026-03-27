# LEMON

LEMON is a conversational workflow engineering platform for building, editing, validating, and executing clinical decision logic.

You can describe logic in natural language (or upload a flowchart), have the assistant build the workflow graph, edit it on a canvas, run stepped execution, and export/compile the result.

## What It Does

- Build workflows from chat with tool-driven graph edits
- Import flowchart images/PDFs into editable workflows
- Edit workflows visually (nodes, edges, conditions, subworkflows)
- Validate workflow structure and expressions
- Execute workflows with streamed, step-by-step runtime events
- Export/import workflow JSON and bundle formats
- Compile workflows to deterministic Python
- Manage reusable workflow packages and public review/voting
- Use authenticated multi-user sessions (cookie-based auth)

## Architecture

| Layer | Main Tech |
| --- | --- |
| Frontend | React 19, TypeScript, Vite, Zustand |
| Backend | FastAPI, Uvicorn, Python 3.10+ |
| LLM Integration | Anthropic SDK with tool use and streaming |
| Streaming | Server-Sent Events (SSE) |
| Persistence | SQLite (`.lemon/`) |
| Authentication | Session cookie + PBKDF2 password hashes |

SSE is the active real-time transport for chat and execution streams.

## Repository Layout

- `src/backend/` - API server, auth, storage, execution engine, tool registry, background tasks
- `src/frontend/` - React UI (canvas, chat, library, export, auth, dev tools)
- `tests/` - backend test suite
- `src/frontend/tests/` - frontend unit and Playwright E2E tests
- `scripts/` - local dev runner, user bootstrap, deployment helpers
- `website/` - static project report content (served at `/report` when present)

## Prerequisites

- Python 3.10+
- Node.js 18+
- [uv](https://github.com/astral-sh/uv)
- Anthropic API key

## Setup

1. Install backend dependencies:

```bash
uv sync
```

2. Install frontend dependencies:

```bash
cd src/frontend && npm install
```

3. Create environment file:

```bash
cp .env.example .env
```

4. Fill required values in `.env`:

```env
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-opus-4-6
# optional
ANTHROPIC_ENDPOINT=
LEMON_ALLOW_REGISTRATION=true
```

## Run In Development

Use the helper script to run backend and frontend together:

```bash
./scripts/dev.sh
./scripts/dev.sh restart
./scripts/dev.sh stop
```

Endpoints:

- Frontend: `http://localhost:5173`
- Backend API: `http://localhost:5001`

Logs and runtime data:

- Log files: `.lemon/logs/`
- SQLite/runtime data: `.lemon/` (or `LEMON_DATA_DIR` if set)

Run services manually if needed:

```bash
python run_api.py
cd src/frontend && npx vite --host
```

## Authentication

- `LEMON_ALLOW_REGISTRATION` controls whether `POST /api/auth/register` is allowed
- Registration is currently API-only (no dedicated frontend sign-up form)
- Sessions are cookie-based (`lemon_session`)
- Password hashing uses PBKDF2-SHA256

If registration is enabled, create users via API:

```bash
curl -X POST http://localhost:5001/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","name":"Your Name","password":"Passw0rd123!","remember":true}'
```

If registration is disabled, create a local user from CLI:

```bash
uv run python scripts/create_user.py --email you@example.com --name "Your Name"
```

## API Surface (High Level)

- Auth: `/api/auth/*`
- Chat streaming and task resume/cancel: `/api/chat/*`
- Workflow CRUD/import/export/public listing: `/api/workflows/*`
- Packages and publishing: `/api/packages/*`
- Validation: `/api/validate`
- Compilation: `/api/workflows/compile*`
- Stepped execution and controls: `/api/workflows/{id}/execute`, `/api/executions/*`
- Dev tool inspection/execution: `/api/tools/*`

## Testing

Backend:

```bash
uv run python -m pytest tests/
```

Frontend unit tests:

```bash
cd src/frontend && npm test
```

Frontend E2E tests:

```bash
cd src/frontend && npm run test:e2e
```

Frontend typecheck:

```bash
cd src/frontend && npx tsc --noEmit
```

## Deployment Notes

- `scripts/start_all.sh` starts the FastAPI app for hosted environments (single port)
- `scripts/deploy_azure.py` builds frontend, packages app, and performs Azure zip deploy

## License

MIT - see `LICENSE`.
