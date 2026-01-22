Known Issues (Development Priorities)

Critical feature correctness issues

1) Orphaned input references
   You can delete a workflow input that is still referenced by nodes.
   Impact: Runtime breakage; nodes point to data that no longer exists.
   Expected: Reject deletion or remove input_ref from nodes.

2) Invalid input references accepted
   Nodes can reference inputs that were never registered.
   Impact: Decisions reference data that will never exist.
   Expected: Validate input_ref against registered inputs.

3) Cycles and self-loops allowed
   Circular graphs (including self-loops) are accepted.
   Impact: Workflow execution can loop forever.
   Expected: Detect and reject cycles or warn prominently.

4) Disconnected subgraphs allowed
   You can add a disconnected chain unrelated to the main flow.
   Impact: Dead/unreachable nodes create confusion.
   Expected: Warn about unreachable nodes or prevent creation.

5) Multiple start nodes allowed
   You can create more than one start node.
   Impact: Ambiguous entry point for execution.
   Expected: Enforce a single start node or require explicit intent.

6) Decision nodes without branches
   Decision nodes can exist without two outgoing edges.
   Impact: Dead-end logic.
   Expected: Require two branches or validate on completion.

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
