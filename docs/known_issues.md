# Known Issues

This document tracks known issues, architectural risks, correctness bugs, and technical debt currently present in the LEMON codebase. It consolidates the previously recorded issues plus the findings from the external GPT review and the follow-up Claude review.

## How to read this document

- Severity reflects likely user impact if the issue is hit.
- Status is informational only; this file is a backlog, not a source of truth for active work.
- File references point to the main code paths involved, not every touched location.

## Severity legend

- `Critical`: can cause the system to reason over the wrong workflow, persist corrupted state, or execute differently across entrypoints.
- `High`: can break correctness, lose user work, or create major drift between frontend, orchestrator, and database state.
- `Medium`: real correctness, UX, or architecture issue with bounded blast radius.
- `Low`: technical debt, resilience gap, or secondary issue worth cleaning up.

## 1. Canonical workflow state is missing during chat

- Severity: `Critical`
- Sources: GPT review, Claude review
- Main files:
  - `src/backend/api/ws_chat.py:355`
  - `src/backend/api/ws_chat.py:363`
  - `src/backend/tools/workflow_edit/helpers.py:739`
- What happens:
  - The visible canvas state is synced into orchestrator memory in `ws_chat.py`.
  - If the workflow does not exist yet, an empty workflow is auto-created in the database.
  - Tool edit helpers load workflow state from the database, not from the in-memory canvas snapshot.
- Why this is a problem:
  - The user can see one graph while tools reason over another.
  - Newly opened or partially edited workflows can be interpreted as empty or stale when tools run.
  - This is the root cause of flowchart drift and incorrect tool reasoning.
- Impact:
  - Tool suggestions, edits, and analysis can target the wrong nodes and edges.
  - Multi-turn refinement can degrade quickly because the LLM is not grounded in the actual visible graph.

## 2. Workflow saves do not persist execution tree

- Severity: `Critical`
- Sources: GPT review, Claude review
- Main files:
  - `src/backend/tools/workflow_edit/helpers.py:857`
  - `src/backend/api/routes/execution_routes.py:68`
  - `src/backend/api/ws_execution.py:374`
- What happens:
  - `save_workflow_changes()` persists nodes, edges, variables, and outputs, but not `tree`.
  - REST execution reads `workflow.tree` from the database.
  - WebSocket execution recomputes the tree from nodes and edges.
- Why this is a problem:
  - The same workflow can execute differently depending on whether it was run through REST or WebSocket.
  - The persisted tree can remain stale indefinitely.
- Impact:
  - Debugging execution becomes unreliable.
  - Production parity between different execution paths is broken.

## 3. Workflow-level output typing is split from output configuration

- Severity: `High`
- Sources: GPT review, Claude review
- Main files:
  - `src/backend/tools/workflow_output/set_output.py:120`
  - `src/backend/validation/workflow_validator.py:402`
  - `src/backend/execution/interpreter.py:903`
- What happens:
  - `set_workflow_output` only saves `outputs`.
  - The validator and interpreter still rely on workflow-level `output_type`.
- Why this is a problem:
  - Output configuration and output typing can diverge.
  - End-node validation and final output casting can operate on stale metadata.
- Impact:
  - Silent type corruption.
  - Broken subprocess contracts.
  - Incorrect final output casting.

## 4. Output casting failures are returned as successful strings

- Severity: `High`
- Sources: Claude review
- Main files:
  - `src/backend/execution/interpreter.py:981`
  - `src/backend/execution/interpreter.py:1022`
- What happens:
  - `_cast_output_value()` catches cast errors and returns a string such as `Error casting to number: ...` instead of raising.
- Why this is a problem:
  - Execution appears successful even when the output is invalid.
  - Callers cannot distinguish real output from a cast failure message.
- Impact:
  - Workflows can silently produce invalid outputs.
  - Downstream automation can accept garbage as valid workflow results.

## 5. Uploaded file context is lost across turns

- Severity: `High`
- Sources: GPT review, Claude review
- Main files:
  - `src/backend/agents/orchestrator.py:582`
- What happens:
  - New uploaded files replace `self.uploaded_files` rather than extending it.
- Why this is a problem:
  - Later turns lose the original source artifact context.
  - Prompt behavior implies persistent file grounding, but runtime state does not preserve it.
- Impact:
  - Reduced fidelity when refining flowcharts extracted from images or documents.

## 6. Node mutation logic is inconsistent across add and modify paths

- Severity: `High`
- Sources: GPT review, Claude review
- Main files:
  - `src/backend/tools/workflow_edit/add_node.py`
  - `src/backend/tools/workflow_edit/helpers.py:396`
  - `src/backend/tools/workflow_edit/modify_node.py`
  - `src/backend/tools/workflow_edit/batch_edit.py`
- What happens:
  - `add_node` uses `build_new_node()` as a shared normalization path.
  - `modify_node` and batch `modify_node` perform raw dict updates and partial validation.
  - Batch modify skips `derive_variables_for_node()` entirely.
- Why this is a problem:
  - Color, label, end-node output config, and derived variable behavior can diverge depending on which tool path was used.
- Impact:
  - The LLM can believe it made a valid edit while execution uses stale or malformed config.

## 7. Variable rename does not update all node references

- Severity: `High`
- Sources: Claude review
- Main files:
  - `src/backend/tools/workflow_input/modify.py:193`
  - `src/backend/tools/workflow_input/modify.py:248`
- What happens:
  - Renaming or retyping a variable regenerates its ID.
  - The tool only returns a warning that callers must update references themselves.
- Why this is a problem:
  - Decision nodes and calculation nodes can retain references to dead variable IDs.
- Impact:
  - Validation failures later in the workflow lifecycle.
  - Broken runtime behavior after apparently successful variable edits.

## 8. Variable removal does not check calculation operand references

- Severity: `High`
- Sources: Claude review
- Main files:
  - `src/backend/tools/workflow_input/remove.py:91`
- What happens:
  - Removal checks `condition.input_id` references in decision nodes.
  - It does not check calculation operands such as `operands[].ref`.
- Why this is a problem:
  - A variable can be deleted even though calculation nodes still depend on it.
- Impact:
  - Runtime interpreter errors.
  - Latent breakage introduced by seemingly valid user actions.

## 9. Read paths perform hidden writes

- Severity: `Medium`
- Sources: Claude review
- Main files:
  - `src/backend/tools/workflow_edit/helpers.py:657`
  - `src/backend/tools/workflow_edit/helpers.py:732`
- What happens:
  - `_rederive_subprocess_variable_types()` is called during workflow load.
  - If it detects stale types, it writes back to the database.
- Why this is a problem:
  - Read operations are no longer side-effect free.
  - Concurrent loads can trigger writes unexpectedly.
- Impact:
  - Harder debugging.
  - Race-condition risk.
  - Surprising state changes from simple reads.

## 10. Post-tool validation happens after mutation and persistence

- Severity: `High`
- Sources: GPT review, Claude review
- Main files:
  - `src/backend/agents/orchestrator.py:360`
  - `src/backend/agents/orchestrator.py:482`
- What happens:
  - Tools can persist changes before orchestrator validation runs.
  - Orchestrator mutates in-memory workflow state before validating.
- Why this is a problem:
  - A validation failure does not roll back persisted or in-memory changes.
- Impact:
  - Invalid workflow state can survive a failed tool action.

## 11. Session state is aliased by reference

- Severity: `High`
- Sources: Claude review, existing CLAUDE guidance
- Main files:
  - `src/backend/agents/orchestrator.py:174`
  - `src/backend/agents/orchestrator.py:322`
  - `src/backend/agents/orchestrator.py:325`
- What happens:
  - `current_workflow` returns a new dict, but the contained `nodes`, `edges`, and related lists are live references.
  - `workflow_analysis` is passed as a direct reference into `session_state`.
- Why this is a problem:
  - Tools can accidentally mutate orchestrator state in place.
  - The exact pass-by-reference pitfalls described in `CLAUDE.md` remain active.
- Impact:
  - Duplicate state updates.
  - Hidden mutation.
  - Non-deterministic tool behavior depending on call path.

## 12. Sync failures and other internal errors are swallowed instead of failing loudly

- Severity: `High`
- Sources: Claude review
- Main files:
  - `src/backend/agents/orchestrator.py:169`
  - `src/backend/agents/orchestrator.py:231`
  - `src/backend/agents/orchestrator.py:266`
  - `src/backend/tools/workflow_edit/helpers.py:293`
- What happens:
  - Several `except Exception` blocks log and continue.
  - Sync failures return early without surfacing hard errors.
  - Some helper failures collapse into empty values such as `[]`.
- Why this is a problem:
  - The system keeps operating on stale or incomplete state.
  - This directly conflicts with the fail-loud requirement in `CLAUDE.md`.
- Impact:
  - Silent drift.
  - Missing user-visible error signals.
  - Misleading tool behavior.

## 13. MCP tool calls are expensive and one code path is incomplete

- Severity: `Medium`
- Sources: GPT review, Claude review
- Main files:
  - `src/backend/mcp_bridge/client.py:97`
  - `src/backend/mcp_bridge/server.py:497`
  - `src/backend/tools/workflow_analysis/update_subworkflow.py:185`
- What happens:
  - Every MCP call initializes a new client session and lists tools again.
  - The `update_subworkflow` MCP handler does not inject required `user_id` and `repo_root`.
- Why this is a problem:
  - Multi-tool loops pay unnecessary overhead.
  - `update_subworkflow` is effectively broken through MCP.
- Impact:
  - Avoidable latency.
  - Tool failure in one of the subworkflow editing paths.

## 14. Frontend persistence is incomplete

- Severity: `High`
- Sources: GPT review, Claude review
- Main files:
  - `src/frontend/src/stores/workflowStore.ts`
- What happens:
  - Most node edits, node moves, edge additions, edge deletions, and sidebar changes remain local-only.
  - Only a narrow subset of edge changes is synced to the backend.
- Why this is a problem:
  - Reloading the page or invoking DB-backed tools can revert the effective source of truth.
- Impact:
  - Stale backend state.
  - Wrong tool reasoning.
  - Lost edits after refresh.

## 15. Workflow browser bypasses canonical transform and hydration

- Severity: `Medium`
- Sources: GPT review
- Main files:
  - `src/frontend/src/components/WorkflowBrowser.tsx:207`
  - `src/frontend/src/utils/canvas/transform.ts:22`
- What happens:
  - `WorkflowBrowser.tsx` loads raw backend nodes and edges directly.
  - It does not use `transformFlowchartFromBackend()`.
- Why this is a problem:
  - Coordinate conversion, label sanitization, and normalization are bypassed.
- Impact:
  - Distorted layouts.
  - Inconsistent frontend rendering compared to the main workflow page.

## 16. Label sanitization invents labels for unlabeled nodes and edges

- Severity: `Medium`
- Sources: GPT review
- Main files:
  - `src/frontend/src/utils/canvas/transform.ts:7`
  - `src/frontend/src/utils/canvas/transform.ts:104`
- What happens:
  - `sanitizeLabel()` falls back to `Node` for missing or empty labels.
  - Edge labels reuse the same fallback.
- Why this is a problem:
  - An unlabeled branch can become visibly labeled as `Node`.
  - The UI invents semantics instead of reflecting the actual graph.
- Impact:
  - Misleading decisions and branch polarity in the UI.

## 17. Validation UI still depends on a legacy blocks model

- Severity: `Medium`
- Sources: GPT review
- Main files:
  - `src/frontend/src/components/Modals.tsx:94`
  - `src/frontend/src/components/WorkflowPage.tsx:137`
- What happens:
  - Validation code reads `currentWorkflow.blocks` for outputs.
  - Live workflows are loaded with `blocks: []` and `connections: []`, while graph data lives elsewhere.
- Why this is a problem:
  - Validation UI is disconnected from the actual graph representation.
- Impact:
  - Incorrect or empty validation options.

n18-21, are iffy, i added them at the end, not high prio for now tho, - axel

## 22. `handle_sync_workflow` lacks conversation ownership validation

- Severity: `Medium`
- Sources: Claude review
- Main files:
  - `src/backend/api/ws_chat.py:661`
- What happens:
  - Workflow sync attaches to a conversation ID without verifying that the current user owns that conversation.
- Why this is a problem:
  - Conversation IDs are random, but authorization still depends on obscurity.
- Impact:
  - Cross-user workflow state interference is possible if a conversation ID is exposed.

## 23. Batch edit modify path allows arbitrary key injection into nodes

- Severity: `Medium`
- Sources: Claude review
- Main files:
  - `src/backend/tools/workflow_edit/batch_edit.py:153`
- What happens:
  - The batch modify path copies all operation keys except `op` and `node_id` into the node dict.
- Why this is a problem:
  - Unexpected keys can be persisted into node objects.
- Impact:
  - Data pollution.
  - Harder reasoning about node schema invariants.

## 24. Tree construction relies on upstream validation for cycle safety

- Severity: `Medium`
- Sources: Claude review
- Main files:
  - `src/backend/utils/flowchart.py`
  - `src/backend/validation/workflow_validator.py:412`
- What happens:
  - Cycle detection exists in validation.
  - `tree_from_flowchart()` itself does not defend against cycles.
- Why this is a problem:
  - New call sites that skip validation can build invalid trees.
- Impact:
  - Execution inconsistencies or malformed trees if validation is bypassed.

## 25. Variable and analysis state can arrive separately in the frontend

- Severity: `Low`
- Sources: Claude review
- Main files:
  - `src/frontend/src/api/socket-handlers/workflowHandlers.ts`
- What happens:
  - Workflow graph changes and analysis changes are emitted as separate events.
- Why this is a problem:
  - If one event is delayed or lost, node state and variable state can drift in the UI.
- Impact:
  - Temporary or persistent inconsistency in side panels and validation views.

## 26. Evals and tests have known coverage and integrity gaps

- Severity: `Medium`
- Sources: GPT review, Claude review, prior known issues
- Main files:
  - `tests/evals/test_scoring.py`
  - `evals/`
- What happens:
  - There is no end-to-end regression for canvas persistence before DB-backed tools.
  - There is no parity test between REST and WebSocket execution.
  - There is no regression for `set_workflow_output` updating workflow-level `output_type`.
  - `tests/evals/test_scoring.py` references missing source under `evals`.
- Why this is a problem:
  - Major correctness regressions can ship unnoticed.
- Impact:
  - Known architecture flaws are not guarded by automated tests.

## 27. Subflow Python export fallback

- Severity: `Low`
- Sources: Existing known issue
- Main files:
  - `src/backend/execution/python_compiler.py:792`
- What happens:
  - Missing or unreachable subflows render as commented placeholders in generated Python.
- Why this is a problem:
  - Export degrades gracefully but requires manual intervention.
- Impact:
  - Generated code can be incomplete.

## 28. Hardcoded temporary directory assumptions may still exist

- Severity: `Low`
- Sources: Existing known issue
- What happens:
  - Some scripts and eval code historically relied on `/tmp` semantics.
- Why this is a problem:
  - Cross-platform brittleness, especially on Windows.
- Impact:
  - Script failures outside Unix-like environments.

## 29. `on_step` interpreter callback payloads have drifted over time

- Severity: `Low`
- Sources: Existing known issue
- Main files:
  - `src/backend/execution/interpreter.py`
- What happens:
  - The callback now emits a mix of node and non-node events.
- Why this is a problem:
  - Consumers and tests can break if they assume only step-indexed node executions.
- Impact:
  - Fragile tests and ambiguous event typing.

## 30. Circular subflow protection exists at runtime, but UI still allows invalid attempts

- Severity: `Low`
- Sources: Existing known issue
- Main files:
  - `src/backend/execution/interpreter.py`
  - frontend subflow selection flows
- What happens:
  - Runtime correctly blocks recursive subflow cycles.
  - The frontend can still let users attempt invalid configurations.
- Why this is a problem:
  - Errors surface late instead of being prevented early.
- Impact:
  - Poor UX around subflow authoring.

## 31. Uploaded files are not lifecycle-managed in storage

- Severity: `Low`
- Sources: Existing known issue, Claude review
- Main files:
  - upload handling paths
- What happens:
  - Uploaded artifacts are retained without cleanup or DB-backed lifecycle tracking.
- Why this is a problem:
  - Storage can grow indefinitely.
- Impact:
  - Long-term disk bloat.

## 32. Error details may leak internal endpoint information to the frontend

- Severity: `Medium`
- Sources: Claude review
- Main files:
  - `src/backend/api/ws_execution.py:402`
  - `src/backend/llm/client.py`
- What happens:
  - Raw exception strings can be emitted to the frontend.
- Why this is a problem:
  - Internal endpoint or infrastructure details can leak through error text.
- Impact:
  - Unnecessary exposure of internal configuration details.

## 33. Long-lived in-memory guidance and upload metadata are not pruned aggressively

- Severity: `Low`
- Sources: Claude review
- Main files:
  - `src/backend/agents/orchestrator.py:61`
  - `src/backend/agents/orchestrator.py:65`
- What happens:
  - Guidance and upload-related metadata can accumulate through long conversations.
- Why this is a problem:
  - Memory usage grows over time, even if bounded in most practical sessions.
- Impact:
  - Low-grade memory pressure and stale context retention.

## 34. Decision branch completeness is only enforced in strict validation

- Severity: `Low`
- Sources: Claude review
- Main files:
  - `src/backend/validation/workflow_validator.py:351`
- What happens:
  - Incremental editing paths allow partially connected decision nodes by design.
- Why this is a problem:
  - Incomplete branch setups can live in the workflow longer than expected.
- Impact:
  - Runtime errors or confusing intermediate states if incomplete workflows are executed too early.

## 35. No dedicated faithfulness eval suite for flowchart extraction quality

- Severity: `Medium`
- Sources: GPT review
- What happens:
  - There is no robust eval coverage for branch polarity, ambiguous labels, multiple images, distractor legend boxes, false positives, or tool-order correctness.
- Why this is a problem:
  - The system can regress on semantic faithfulness even if structure-level tests pass.
- Impact:
  - Lower trust in extracted and refined workflows.

## Notes on overlap

- Several issues share the same root cause: missing canonical state, duplicated mutation logic, and incomplete persistence.
- Fixing the save pipeline and state-sync model should remove multiple symptoms at once.
- Some frontend issues are legacy-shape problems that should be deleted outright rather than preserved for backward compatibility.



## 18. Undo history is polluted by server-driven updates and duplicate pushes

- Severity: `Medium`
- Sources: GPT review
- Main files:
  - `src/frontend/src/components/Canvas.tsx:623`
  - `src/frontend/src/api/socket-handlers/workflowHandlers.ts`
- What happens:
  - Some operations push history twice.
  - Socket-driven updates call store mutators that also push history.
- Why this is a problem:
  - User undo history records system-driven state transitions as if they were local edits.
- Impact:
  - Confusing undo/redo behavior.

## 19. WebSocket disconnects can drop user messages and workflow updates

- Severity: `High`
- Sources: Claude review
- Main files:
  - `src/frontend/src/api/socket.ts:43`
  - `src/backend/api/ws_chat.py`
  - `src/backend/api/ws_execution.py`
- What happens:
  - Outgoing messages are discarded when disconnected.
  - Backend tasks can continue while the frontend misses all emitted events during a disconnect.
  - Reconnect does not replay missed workflow updates.
- Why this is a problem:
  - The user can lose commands, progress updates, and state refresh events.
- Impact:
  - Lost work perception.
  - Stale UI after reconnect.
  - Tool or execution progress that becomes invisible.

## 20. WebSocket resume and reconnect behavior is incomplete

- Severity: `Medium`
- Sources: Claude review
- Main files:
  - `src/frontend/src/api/socket.ts:114`
  - `src/backend/api/ws_chat.py:694`
  - `src/backend/api/ws_execution.py`
- What happens:
  - Reconnect attempts stop after a fixed maximum.
  - Chat tasks can be rebound to a new connection, but missed events are not replayed.
  - Execution tasks do not expose an equivalent resume flow.
- Why this is a problem:
  - Mid-run disconnects have poor recovery characteristics.
- Impact:
  - Users must refresh to recover.
  - Running executions can become detached from the frontend.

## 21. Concurrent workflow editing uses last-write-wins

- Severity: `Medium`
- Sources: Claude review
- Main files:
  - `src/backend/storage/workflows.py:421`
  - `src/frontend/src/api/socket-handlers/workflowHandlers.ts`
- What happens:
  - Workflow updates do not use optimistic concurrency control.
  - Two tabs can overwrite each other silently.
- Why this is a problem:
  - There is no conflict detection or merge protection.
- Impact:
  - Lost edits.
  - Non-deterministic state when multiple sessions edit the same workflow.