# Image Eval Harness

This directory contains offline evaluation tooling for measuring image-to-workflow extraction quality across:
- `workflow_test.jpeg`
- `Diabetes Treatment .png`
- `Liver Pathology .png`

## Commands

Smoke run (1 trial per case):

```bash
python /Users/jeetthakwani/dev/LEMON/evals/run_image_eval.py --cases all --trials 1
```

Full run (3 trials per case + diagnostics):

```bash
python /Users/jeetthakwani/dev/LEMON/evals/run_image_eval.py --cases all --trials 3 --emit-report
```

Run through MCP HTTP API transport:

```bash
python /Users/jeetthakwani/dev/LEMON/evals/run_image_eval.py --cases all --trials 3 --emit-report --transport mcp
```

Run specific case IDs only:

```bash
python /Users/jeetthakwani/dev/LEMON/evals/run_image_eval.py --cases workflow_test,diabetes_treatment --trials 3 --emit-report
```

## Artifacts

For each run ID, outputs are written to:

- `evals/results/<run_id>/summary.json`
- `evals/results/<run_id>/failures.jsonl` (when `--emit-report`)
- `evals/results/<run_id>/report.md` (when `--emit-report`)
- `evals/results/<run_id>/<case_id>/trial_XX/raw_model_output.txt`
- `evals/results/<run_id>/<case_id>/trial_XX/normalized_analysis.json`
- `evals/results/<run_id>/<case_id>/trial_XX/flowchart.json`
- `evals/results/<run_id>/<case_id>/trial_XX/score.json`

## Isolation

The runner sets:
- `LEMON_DATA_DIR=/tmp/lemon_eval_<run_id>`
- `LEMON_INCLUDE_RAW_ANALYSIS=1`

This keeps eval state (uploads/history/token files) out of the tracked `.lemon/` directory.

## Scoring

Per-trial metrics:
- `node_f1`
- `edge_f1`
- `variable_f1`
- `output_f1`
- `semantic_score`
- `validity_score`

Composite score:
- `0.25 * node_f1`
- `0.25 * edge_f1`
- `0.15 * variable_f1`
- `0.10 * output_f1`
- `0.20 * semantic_score`
- `0.05 * validity_score`

Composite is reported in points (`0-100`) in `summary.json`.
