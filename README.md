# LEMON

LEMON converts a **workflow diagram (image)** into **deterministic Python code** by:\n
- extracting a typed workflow model (inputs/decision points/outputs)\n
- generating comprehensive test cases\n
- iteratively generating Python until it passes the labeled tests\n
- validating on additional edge cases\n
\nThe core implementation lives in `src/lemon/`.\n
\n## Requirements\n
- Python 3.9+\n
- `uv` (recommended) or pip\n
- Anthropic credentials + E2B sandbox key\n
\n## Setup\n
Create a `.env` in repo root:\n
```\n+ENDPOINT=...\n+DEPLOYMENT_NAME=...\n+API_KEY=...\n+E2B_API_KEY=...\n+HAIKU_DEPLOYMENT_NAME=...  # optional\n+```\n
Install deps (recommended):\n
```bash\n+uv pip install -r requirements.txt\n+```\n
\n## Run the pipeline\n
```bash\n+uv run python refine_workflow_code.py --workflow-image workflow.jpeg --max-iterations 5\n+```\n
This will (re)create **generated artifacts** (gitignored):\n
- `workflow_analysis.json`\n+- `workflow_inputs.json`\n+- `workflow_outputs.json`\n+- `tests.json`\n+- `final_tests.json`\n+- `generated_code.py`\n+\nTo validate the generated code against labeled tests:\n
```bash\n+uv run python run_tests.py\n+```\n
\n## Analyze workflow only\n
```bash\n+uv run python main.py\n+```\n
\n## Frontend demo\n
```bash\n+uv run python frontend/app.py\n+```\n
Then open `http://localhost:5000`.\n
\n## Repo layout\n
```\n+LEMON/\n+├── src/lemon/                 # new core package\n+│   ├── analysis/              # workflow image → WorkflowAnalysis\n+│   ├── generation/            # WorkflowAnalysis → Python code\n+│   ├── testing/               # test-case generation + sandbox harness\n+│   ├── core/                  # pipeline orchestration + domain models\n+│   └── api/                   # Anthropic + E2B integrations\n+├── src/utils/                 # legacy compatibility wrappers\n+├── refine_workflow_code.py    # CLI entrypoint → RefinementPipeline\n+├── main.py                    # analysis-only CLI\n+├── frontend/                  # Flask + SSE demo UI\n+└── tests/                     # pytest unit tests\n+```\n
\n## Development\n
Formatting / linting:\n
```bash\n+uv run python -m black .\n+uv run python -m isort .\n+uv run python -m mypy --explicit-package-bases --namespace-packages src\n+``` \n*** End Patch"}"}}

