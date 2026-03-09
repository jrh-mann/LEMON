# Fix Plan

This document turns the known issues backlog into a practical remediation plan. It is intentionally opinionated: the goal is to remove root causes first, not patch individual symptoms one by one.

## Guiding principles

- Make the workflow state canonical before fixing downstream symptoms.
- Centralize mutation and persistence logic instead of maintaining parallel code paths.
- Fail loudly when state sync or persistence breaks.
- Prefer deleting legacy paths over adding compatibility layers.
- Add integration tests for every fixed root cause before moving on.

## Acceptance criteria for the overall effort

- Tool reasoning uses the same workflow state the user sees on the canvas.
- REST and WebSocket execution produce identical results for the same workflow.
- Workflow saves persist all execution-critical state.
- Variable, output, and node mutations preserve referential integrity.
- Frontend reconnects and sync behavior do not silently lose user work.
- New tests cover orchestrator, tool, persistence, and execution parity flows.

## Phase 1. Canonical state before tool execution

- Priority: `P0`
- Goal: remove the most dangerous source of drift.

### Problems addressed

- `docs/known_issues.md` items 1, 5, 10, 11, 12, 14

### Changes

- Add a single pre-tool synchronization path in `src/backend/api/ws_chat.py` that persists the current canvas snapshot before any DB-backed tool call.
- Make the orchestrator fail loudly if workflow sync or analysis sync fails instead of logging and continuing.
- Deep-copy `nodes`, `edges`, `variables`, `outputs`, and `workflow_analysis` when building `session_state` in `src/backend/agents/orchestrator.py`.
- Ensure the workflow auto-create path does not leave an empty placeholder as the effective DB truth once a real canvas snapshot exists.
- Preserve uploaded file context across turns rather than replacing it with only the newest files.

### Tests

- Integration test: canvas state is persisted before a workflow edit tool runs.
- Integration test: orchestrator tool execution uses the latest canvas snapshot, not stale DB state.
- Integration test: uploaded files remain available across multiple turns.
- Failure test: sync failure raises a visible error and does not continue with stale state.

### Done when

- A user can edit on the canvas, invoke a tool immediately, and the tool sees the exact same graph.
- Sync errors stop the action instead of degrading silently.

## Phase 2. Unified save pipeline

- Priority: `P0`
- Goal: make persistence atomic and execution-safe.

### Problems addressed

- `docs/known_issues.md` items 2, 3, 4, 6, 9, 10, 24

### Changes

- Expand `save_workflow_changes()` in `src/backend/tools/workflow_edit/helpers.py` to handle:
  - `nodes`
  - `edges`
  - `variables`
  - `outputs`
  - `tree`
  - `output_type`
- Recompute `tree` from nodes and edges inside the save pipeline, not in scattered callers.
- Validate workflow state before persisting, or persist transactionally with explicit rollback on validation failure.
- Remove hidden write side-effects from read helpers such as `_rederive_subprocess_variable_types()`.
- Make output casting raise a hard interpreter error instead of returning an error string.

### Tests

- Integration test: a tool save recomputes and persists `tree`.
- Integration test: `set_workflow_output` updates workflow-level `output_type` and related output config together.
- Regression test: invalid output cast fails loudly.
- Regression test: loading a workflow does not write to the database.

### Done when

- Execution-critical fields are always saved together.
- Failed validation cannot leave partially valid persisted state behind.

## Phase 3. Mutation normalization and referential integrity

- Priority: `P0`
- Goal: ensure all edit paths produce the same valid workflow schema.

### Problems addressed

- `docs/known_issues.md` items 6, 7, 8, 23, 34

### Changes

- Extract a shared normalization function for node edits and use it from:
  - `src/backend/tools/workflow_edit/add_node.py`
  - `src/backend/tools/workflow_edit/modify_node.py`
  - `src/backend/tools/workflow_edit/batch_edit.py`
- Make batch `modify_node` call the same derived-variable update logic as standalone `modify_node`.
- Add a workflow-wide variable reference updater for variable renames and type-driven ID changes.
- Validate variable removal against:
  - decision conditions
  - calculation operand references
  - any other variable-reference fields in node config
- Replace batch-edit blacklist merging with an explicit whitelist of allowed mutable node fields.

### Tests

- Integration test: modifying a calculation node through standalone and batch paths yields the same variable set.
- Integration test: renaming a variable updates all decision and calculation references.
- Regression test: removing a referenced variable fails with a clear error.
- Regression test: batch edit rejects unknown node keys.

### Done when

- There is one normalization model for node creation and modification.
- Variable references stay valid after edits.

## Phase 4. REST and WebSocket execution parity

- Priority: `P1`
- Goal: execution is deterministic across entrypoints.

### Problems addressed

- `docs/known_issues.md` items 2, 3, 4, 24, 26

### Changes

- Keep REST and WebSocket execution on the same canonical tree semantics.
- Decide one clear policy for WebSocket execution:
  - execute persisted canonical state, or
  - execute the latest validated unsaved canvas snapshot using the same tree builder and validator as REST.
- Ensure both entrypoints use the same validation contract and output typing rules.

### Tests

- Parity test: same workflow, same inputs, REST and WebSocket produce identical outputs and step traces.
- Parity test: invalid workflow fails the same way on both entrypoints.

### Done when

- Entry point no longer changes behavior.

## Phase 5. Frontend graph hydration and legacy model cleanup

- Priority: `P1`
- Goal: remove graph-shape drift and delete obsolete frontend assumptions.

### Problems addressed

- `docs/known_issues.md` items 15, 16, 17, 25

### Changes

- Update `src/frontend/src/components/WorkflowBrowser.tsx` to use `transformFlowchartFromBackend()`.
- Change `sanitizeLabel()` in `src/frontend/src/utils/canvas/transform.ts` to preserve empty labels instead of inventing `Node`.
- Remove or refactor legacy `blocks` and `connections` fields in frontend workflow state.
- Make validation UI read from the canonical graph/analysis model rather than the obsolete block model.
- Where possible, collapse graph update and analysis update into a single coherent frontend refresh path.

### Tests

- Frontend test: backend graph opens identically in browser and workflow page views.
- Frontend test: unlabeled edges stay unlabeled.
- Frontend test: validation UI reflects live graph outputs.

### Done when

- The frontend uses one graph model everywhere.
- The UI no longer invents branch meaning.

## Phase 6. WebSocket resilience and recovery

- Priority: `P1`
- Goal: make disconnects survivable.

### Problems addressed

- `docs/known_issues.md` items 18, 19, 20, 21, 25

### Changes

- Add an outgoing message queue in `src/frontend/src/api/socket.ts` so user actions are not discarded while disconnected.
- Add replayable event sequencing for chat and workflow update events.
- Add an execution resume flow comparable to chat resume.
- Replace dead-end reconnect exhaustion with a user-triggerable retry path.
- Use silent store mutation paths for socket-driven updates to keep undo history clean.

### Tests

- Frontend integration test: message sent during disconnect is delivered after reconnect.
- Integration test: workflow updates emitted during a disconnect are replayed on resume.
- Integration test: execution can be resumed after connection loss.
- Regression test: server-driven updates do not pollute local undo history.

### Done when

- A temporary disconnect no longer causes silent message loss or stale workflow state.

## Phase 7. MCP and authorization hardening

- Priority: `P1`
- Goal: remove broken or insecure edge paths.

### Problems addressed

- `docs/known_issues.md` items 13, 22, 32

### Changes

- Reuse MCP sessions or cache tool schemas in `src/backend/mcp_bridge/client.py`.
- Fix `update_subworkflow` session injection in `src/backend/mcp_bridge/server.py`.
- Add conversation ownership validation in `src/backend/api/ws_chat.py` sync handlers.
- Sanitize or map internal exceptions before sending them to the frontend.

### Tests

- Integration test: `update_subworkflow` succeeds via MCP.
- Authorization test: a user cannot sync into another user's conversation.
- Regression test: frontend receives safe error messages without leaking internal endpoints.

### Done when

- Broken MCP tool paths are fixed.
- Authorization no longer depends on opaque IDs.

## Phase 8. Concurrency and multi-tab safety

- Priority: `P2`
- Goal: prevent silent last-write-wins data loss.

### Problems addressed

- `docs/known_issues.md` items 21, 31, 33

### Changes

- Add workflow versioning or `updated_at` optimistic concurrency checks in `src/backend/storage/workflows.py`.
- Reject stale writes with explicit conflict errors.
- Decide on frontend conflict UX for same-workflow multi-tab editing.
- Add cleanup policy for uploaded artifacts and stale conversation-associated assets.

### Tests

- Integration test: stale write is rejected when another tab has already saved.
- Integration test: conflict response is surfaced clearly in the frontend.
- Maintenance test or script coverage for upload cleanup.

### Done when

- Multi-tab editing no longer silently overwrites newer data.

## Phase 9. Evals and regression harness rebuild

- Priority: `P2`
- Goal: stop these problems from returning.

### Problems addressed

- `docs/known_issues.md` items 26, 29, 35

### Changes

- Restore or delete broken eval imports under `evals/` and `tests/evals/`.
- Build end-to-end regression coverage for:
  - canvas persistence before tool calls
  - REST/WS execution parity
  - output-type synchronization
  - variable reference integrity
  - reconnect/replay behavior
- Add faithfulness evals for:
  - branch polarity
  - ambiguous labels
  - multiple source images
  - distractor legend boxes
  - false positive extraction
  - tool-order correctness

### Tests

- All of the above are the test plan.

### Done when

- The major architectural bugs identified in this audit are explicitly guarded by tests.

## Recommended implementation order

1. Phase 1: Canonical state before tool execution
2. Phase 2: Unified save pipeline
3. Phase 3: Mutation normalization and referential integrity
4. Phase 4: REST and WebSocket execution parity
5. Phase 5: Frontend graph hydration and legacy cleanup
6. Phase 6: WebSocket resilience and recovery
7. Phase 7: MCP and authorization hardening
8. Phase 8: Concurrency and multi-tab safety
9. Phase 9: Evals and regression harness rebuild

## Fast follow fixes worth doing immediately

- Fix `update_subworkflow` MCP injection bug.
- Fix `WorkflowBrowser.tsx` to use canonical transform.
- Stop `sanitizeLabel()` from inventing `Node` labels.
- Remove the duplicate edge-history push in `Canvas.tsx`.
- Make `_cast_output_value()` raise instead of returning error strings.
- Fix `batch_edit` modify path to update derived variables.

## Work style recommendation

- Take one phase at a time.
- For each phase:
  - write the failing integration tests first
  - implement the minimal fix
  - verify both tool-isolated and orchestrator-mediated flows
  - commit before moving to the next phase

This plan deliberately favors root-cause removal over broad patching. If Phase 1 and Phase 2 are done well, a large share of the current issue list should disappear naturally.
