## LEMON

LEMON converts a **workflow diagram (image)** into **deterministic Python code** by:
- extracting a structured workflow model (inputs / decision points / outputs)
- generating comprehensive test cases
- iteratively generating Python until it passes labeled tests
- validating on additional edge cases

The core implementation lives in `src/lemon/`.

### Requirements
- Python 3.9+
- [`uv`](https://github.com/astral-sh/uv) recommended (works with your `.venv`)
- Anthropic credentials + E2B sandbox key

### Setup

1) Create a `.env` in the repo root:

```
AZURE_OPENAI_ENDPOINT=https://newlemon.cognitiveservices.azure.com/
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_API_VERSION=2024-12-01-preview
DEPLOYMENT_NAME=gpt-5
E2B_API_KEY=...
HAIKU_DEPLOYMENT_NAME=...  # optional (used for test labeling)
```

2) Install dependencies:

```bash
uv pip install -r requirements.txt
```

### Run the full pipeline (end-to-end)

```bash
uv run python refine_workflow_code.py --workflow-image workflow.jpeg --max-iterations 5
```

This will (re)create generated artifacts (gitignored):
- `workflow_analysis.json`
- `workflow_inputs.json`
- `workflow_outputs.json`
- `tests.json`
- `final_tests.json`
- `generated_code.py`

### Validate the generated code against labeled tests

```bash
uv run python run_tests.py
```

### Analyze workflow only (no refinement loop)

```bash
uv run python main.py
```

### Frontend demo

```bash
uv run python frontend/app.py
```

Then open `http://localhost:5000`.

### Repo layout

```
LEMON/
├── src/lemon/                 # core package
│   ├── analysis/              # workflow image → WorkflowAnalysis
│   ├── generation/            # WorkflowAnalysis → Python code
│   ├── testing/               # test-case generation + sandbox harness
│   ├── core/                  # pipeline orchestration + domain models
│   └── api/                   # Anthropic + E2B integrations
├── src/utils/                 # legacy compatibility wrappers
├── refine_workflow_code.py    # CLI entrypoint → RefinementPipeline
├── main.py                    # analysis-only CLI
├── generate_test_cases.py     # test-case generator CLI (from workflow_inputs.json)
├── run_tests.py               # validates generated_code.py vs tests.json
├── workflow_prompts.py        # analysis prompt templates (repo-level)
├── frontend/                  # Flask + SSE demo UI
└── tests/                     # pytest unit tests
```

### Development

```bash
uv run python -m black .
uv run python -m isort .
uv run python -m mypy --explicit-package-bases --namespace-packages src
```
