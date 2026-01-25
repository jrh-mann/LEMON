Known Issues (Development Priorities)

Critical feature correctness issues

1) [FIXED] Orphaned input references
   Deletion of workflow inputs now validates for references.
   Impact: Prevents nodes from referencing deleted inputs.
   Fixed: remove_workflow_input.py:63-88 checks for referencing nodes before deletion.
          By default, deletion fails if references exist. Use force=true to cascade delete.

2) [FIXED] Invalid input references accepted
   Nodes can reference inputs that were never registered.
   Impact: Decisions reference data that will never exist.
   Expected: Validate input_ref against registered inputs.

3) [FIXED] Cycles and self-loops allowed
   Cycles and self-loops are now detected and rejected.
   Impact: Workflow execution cannot loop forever.
   Fixed: workflow_validator.py:221-239 detects self-loops (always enforced).
          workflow_validator.py:241-451 detects multi-node cycles using DFS (always enforced).
          Both checks run in lenient and strict modes.


4) [FIXED] Disconnected subgraphs allowed
   Unreachable nodes are now detected in strict validation.
   Impact: Strict mode prevents disconnected/unreachable nodes.
   Fixed: workflow_validator.py:278-292 uses BFS to find unreachable nodes (strict mode only).
          Note: Tools use strict=False, so unreachable nodes can be created incrementally,
          but final validation with validate_workflow will catch them.

5) [FIXED] Multiple start nodes allowed
   Multiple start nodes are now rejected.
   Impact: Validation prevents ambiguous entry points.
   Fixed: workflow_validator.py:201-209 always enforces single start node.

6) [FIXED] Decision nodes without branches
   Decision nodes must have at least 2 outgoing edges in strict mode.
   Impact: Validation prevents dead-end logic.
   Fixed: workflow_validator.py:304-322 enforces branch requirements and true/false labels.

Optional design and UX issues

7) Auto-positioning stacks nodes at (0,0)
   Nodes without coordinates overlap at the origin.
   Impact: Users can’t see multiple nodes.
   Expected: Simple auto-layout or vertical spacing.

8) Deleting start node is allowed
   Users can remove the entry point.
   Impact: Workflow becomes invalid but sometimes intentional.
   Expected: Warn or block depending on product direction.

9) Decision nodes can be created outside batch_edit
   Single add_node for decision works despite docs.
   Impact: Inconsistent expectations.
   Expected: Either allow and document, or enforce batch-only.

10) Batch add_connection field strictness
    batch_edit_workflow requires "from"/"to" instead of "from_node_id"/"to_node_id".
    Impact: Easy to make mistakes; errors are cryptic.
    Expected: Accept both or improve error messages.

11) Case sensitivity inconsistencies
    Inputs are case-insensitive; node label matching may not be.
    Impact: Confusing user experience.
    Expected: Document or normalize behavior.

12) No undo or version history
    Deletions are permanent.
    Impact: Recovery is manual.
    Expected: Optional future enhancement.

13) Temp ID pattern not enforced
    Temp IDs are flexible and not restricted to a prefix.
    Impact: Low; currently fine.
    Expected: Optional documentation update only.

Low-priority validation and security (deferred in dev)

14) Label sanitization
    Labels accept raw HTML/JS-like content.
    Impact: Potential XSS if rendered unsafely.
    Expected: Escape or sanitize on render.

15) No label length limits
    Very long labels are accepted.
    Impact: UI and storage bloat.
    Expected: Reasonable limits.

16) No coordinate bounds
    Nodes can be placed far off-canvas.
    Impact: Hard to find nodes.
    Expected: Clamp or warn.

17) Empty or whitespace labels
    Blank labels are accepted.
    Impact: Invisible nodes.
    Expected: Require non-empty labels.

18) Invalid numeric ranges
    Range min can exceed max.
    Impact: Impossible inputs.
    Expected: Validate min <= max.
    Status: CONFIRMED - add_workflow_input.py:102-110 accepts min/max without validation.

New issues discovered (2026-01-25)

19) Validation mode inconsistency in tools
    All workflow edit tools use strict=False (lenient mode) for validation.
    Impact: Tools allow incomplete workflows (no start node, incomplete decision branches).
           This enables incremental construction but means final validation must be explicit.
    Expected: This is intentional for UX, but users must call validate_workflow before execution.
    Location: All tools in workflow_edit/ use strict=False validation.

20) No enforcement of workflow completeness before execution
    Users can attempt to execute invalid workflows unless they explicitly validate first.
    Impact: Runtime errors if workflow is incomplete.
    Expected: Execution should auto-validate with strict=True before running.

21) Condition syntax errors silently ignored during node creation
    Invalid decision node conditions are caught but allow node creation to proceed.
    Impact: workflow_validator.py:137-146 catches ParseError and adds validation error,
            but validation continues. In strict=False mode (used by tools), this allows
            invalid conditions to be saved.
    Expected: Either reject invalid conditions immediately or warn more prominently.
