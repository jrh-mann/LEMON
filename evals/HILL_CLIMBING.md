# Anti-Goodhart Hill Climbing Protocol

## Goal
Improve image-to-workflow conversion quality across all three eval images without overfitting to one diagram.

## Baseline
1. Run baseline on all 3 cases with 3 trials each.
2. Save `summary.json`, `failures.jsonl`, and `report.md`.
3. Record baseline aggregate and per-case composite scores in `evals/results/iteration_log.md`.

## Iteration Loop
1. Review `report.md` and `failures.jsonl`.
2. Choose one failure pattern that appears in at least 2 images.
3. Make one small scaffold/prompt/harness change only.
4. Re-run full eval (`--cases all --trials 3 --emit-report`).
5. Compare against previous accepted run.

## Acceptance Gate
Accept the change only if all are true:
- Overall composite improves by at least **1.0 point**.
- No single case regresses by more than **1.0 point**.
- `semantic_score` does not drop for any case.

If any gate fails, revert the change and try a different fix.

## Allowed Change Scope
- Prioritize fixes in:
  - `src/backend/agents/subagent.py`
  - `src/backend/utils/analysis.py`
- Keep changes general and avoid case-specific hacks tied to one image.

## Logging Format
Append each iteration to `evals/results/iteration_log.md`:
- Timestamp
- Run ID
- Change summary
- Aggregate composite (before -> after)
- Per-case composites (before -> after)
- Semantic scores (before -> after)
- Decision: accepted/rejected
- Notes on observed failure patterns
