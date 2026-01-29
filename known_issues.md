# Known Issues (Development Priorities)

Last updated: 2026-01-29

## Active Issues

### Validation & Execution

**1. Validation mode inconsistency in tools**
All workflow edit tools use `strict=False` (lenient mode) for validation.
- Impact: Tools allow incomplete workflows (no start node, incomplete decision branches). This enables incremental construction but means final validation must be explicit.
- Expected: Intentional for UX. Users must call `validate_workflow` before execution.
- Location: All tools in `tools/workflow_edit/` use `strict=False`.

**2. No enforcement of workflow completeness before execution**
Users can attempt to execute invalid workflows unless they explicitly validate first.
- Impact: Runtime errors if workflow is incomplete.
- Expected: Execution should auto-validate with `strict=True` before running.
- Location: `execution/interpreter.py` should call validator.

**3. Condition syntax errors silently allowed during node creation**
Invalid decision node conditions are caught but allow node creation to proceed in lenient mode.
- Impact: `workflow_validator.py:137-146` catches ParseError and adds validation error, but in `strict=False` mode (used by tools), invalid conditions are saved.
- Expected: Either reject invalid conditions immediately or warn more prominently.

**4. Invalid numeric ranges accepted**
Range `min` can exceed `max` when creating number variables.
- Impact: Creates impossible input constraints.
- Expected: Validate `min <= max` in `add_workflow_variable.py`.
- Location: `add_workflow_variable.py` accepts min/max without validation.

### UX & Design

**5. Auto-positioning stacks nodes at (0,0)**
Nodes without explicit coordinates overlap at origin.
- Impact: Users can't see multiple nodes when created via tools without coordinates.
- Expected: Simple auto-layout or vertical spacing algorithm.
- Location: `add_node.py`, `batch_edit_workflow.py` should provide defaults.

**6. Deleting start node is allowed**
Users can remove the workflow entry point.
- Impact: Workflow becomes invalid (caught by strict validation).
- Expected: Warn or block depending on product direction.

**7. Batch add_connection field strictness**
`batch_edit_workflow` requires `from`/`to` instead of `from_node_id`/`to_node_id`.
- Impact: Easy to make mistakes; errors are cryptic.
- Expected: Accept both field names or improve error messages.

**8. No undo or version history**
Deletions are permanent within a session.
- Impact: Recovery is manual (requires browser refresh to reload last saved state).
- Expected: Optional future enhancement.

### Code Quality

**9. Canvas.tsx size**
`Canvas.tsx` is 1536 lines handling rendering, interaction, and state.
- Impact: Difficult to maintain and test.
- Expected: Split into smaller components (NodeRenderer, EdgeRenderer, SelectionManager, etc.).

**10. Magic numbers for layout**
Layout constants (node sizes, spacing, grid) scattered across files.
- Impact: Inconsistent behavior, hard to adjust.
- Expected: Centralize in a layout config file.

**11. Coordinate system mismatch**
Backend uses top-left coordinates; frontend uses center coordinates.
- Impact: Requires transformation on every sync. Easy to introduce bugs.
- Location: `utils/canvas/transform.ts` handles conversion.
- Expected: Document clearly or unify to single system.

### Architecture & Policy

**12. Backwards compatibility patterns vs CLAUDE.md policy**
The CLAUDE.md states "NEVER implement backwards compatibility" yet multiple patterns exist:
- Tool aliases: `add_workflow_input` → `add_workflow_variable` (3 tools)
- Database column `inputs` exposes as API key `variables`
- Interpreter accepts both `variables` and `inputs` keys
- Legacy ID format `input_age_int` still supported alongside `var_age_int`
- Routes accept both `variables` and `inputs` in payloads
- Migration helper `ensure_workflow_analysis()` converts legacy to new format
- Impact: Creates confusion about when backwards compat is acceptable.
- Expected: Either update CLAUDE.md to document these exceptions, or plan migration to remove all fallbacks.
- Note: These exceptions exist for valid reasons (database stability, LLM tool naming stability) but conflict with stated policy.

### Type Safety

**13. LSP type errors (non-blocking)**
Several type annotation issues that don't affect runtime:
- `Flask-SocketIO`'s `request.sid` not recognized by type checker
- MCP server response types incomplete
- Some dict accesses without proper typing

Impact: IDE warnings, no runtime issues. Low priority.

## Low Priority (Deferred)

**14. Label sanitization**
Labels accept raw HTML/JS-like content.
- Impact: Potential XSS if rendered unsafely.
- Expected: Escape or sanitize on render.
- Status: React's JSX escaping provides protection, but explicit sanitization recommended.

**15. No label length limits**
Very long labels are accepted.
- Impact: UI and storage bloat, canvas rendering issues.
- Expected: Reasonable limits (e.g., 200 chars).

**16. No coordinate bounds**
Nodes can be placed far off-canvas.
- Impact: Hard to find nodes, poor UX.
- Expected: Clamp or warn on extreme values.

**17. Empty or whitespace labels**
Blank labels are accepted.
- Impact: Invisible/confusing nodes.
- Expected: Require non-empty trimmed labels.

**18. Case sensitivity inconsistencies**
Variable names are case-insensitive in some places but not others.
- Impact: Confusing user experience.
- Expected: Document or normalize behavior.

---

## Recently Fixed (2026-01-29)

The following issues were fixed in this session:

1. **Variable sync between frontend and backend** - Frontend analysis (variables) now properly syncs to backend via chat messages and `sync_workflow` events.

2. **Save workflow validation failure** - Save endpoint now uses correct `variables` key when calling validator.

3. **Subprocess output variable validation** - Validator now recognizes `output_variable` from subprocess nodes as valid variables for end node templates.

## Previously Fixed

- Orphaned input references (validated before deletion)
- Invalid input references (validated against registered inputs)
- Cycles and self-loops (detected and rejected)
- Disconnected subgraphs (strict mode only)
- Multiple start nodes (rejected)
- Decision nodes without branches (strict mode validation)
