# Iteration Log

## Template
- Timestamp:
- Run ID:
- Change:
- Aggregate composite: before -> after
- Per-case composite: before -> after
- Per-case semantic score: before -> after
- Decision: accepted/rejected
- Notes:

## Iteration 1
- Timestamp: 2026-02-23T19:33:30.991448+00:00
- Run ID: iter1_prompt_conditions_sonnet46
- Change: prompt update in `subagent.py` to enforce canonical input names, explicit decision `condition` objects, and binary branch labels as `true`/`false`.
- Aggregate composite: 12.08 -> 17.98
- Per-case composite: workflow_test 18.35 -> 24.48; diabetes_treatment 11.37 -> 18.83; liver_pathology 6.53 -> 10.64
- Per-case semantic score: workflow_test 0.00 -> 0.00; diabetes_treatment 0.00 -> 0.00; liver_pathology 0.00 -> 0.00
- Decision: accepted
- Notes: Meets acceptance criteria (overall +5.90, no case regression).

## Iteration 2
- Timestamp: 2026-02-23T20:06:51.856840+00:00
- Run ID: iter2_infer_variables_sonnet46_retry1
- Change: analysis normalization update to infer variables from tree `condition.input_id`/`input_ids`, and backfill node `input_ids` from conditions.
- Aggregate composite: 17.98 -> 28.84
- Per-case composite: workflow_test 24.48 -> 44.45; diabetes_treatment 18.83 -> 27.52; liver_pathology 10.64 -> 14.57
- Per-case semantic score: workflow_test 0.00 -> 48.72; diabetes_treatment 0.00 -> 13.89; liver_pathology 0.00 -> 4.17
- Decision: accepted
- Notes: Meets acceptance criteria (overall +10.86, no case regression, semantic improved on all cases). Observed intermittent MCP run failure modes during attempts: one 120s timeout and one one-off `list index out of range` tool error; successful retry completed with `LEMON_MCP_TIMEOUT=300`.

## Iteration 3
- Timestamp: 2026-02-23T20:24:13.028760+00:00
- Run ID: iter3_flow_node_only_sonnet46
- Change: prompt tweak to exclude non-flow annotation/legend nodes unless explicitly arrow-connected.
- Aggregate composite: 28.84 -> 27.50
- Per-case composite: workflow_test 44.45 -> 38.65; diabetes_treatment 27.52 -> 27.49; liver_pathology 14.57 -> 16.37
- Per-case semantic score: workflow_test 48.72 -> 46.15; diabetes_treatment 13.89 -> 16.67; liver_pathology 4.17 -> 16.67
- Decision: rejected
- Notes: Fails acceptance criteria (overall dropped by 1.34, workflow_test regressed by 5.80, workflow_test semantic score decreased). Change reverted to keep iteration 2 as best known config.
