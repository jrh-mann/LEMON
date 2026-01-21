Detailed Weird Behaviors & Vulnerabilities Report
🔴 CRITICAL ISSUES
1. Orphaned Input References

    What happens: You can delete a workflow input that nodes are actively referencing
    Test case:
        Created decision node with input_ref='Patient Age'
        Deleted 'Patient Age' input → Success ✓
        Node still exists with dangling reference
    Impact: Workflow runtime would break; no way for users to provide that input anymore
    Expected: Should reject deletion OR auto-remove input_ref from nodes

2. Invalid Input References Accepted

    What happens: Can set input_ref to inputs that don't exist
    Test case:
        Created node with input_ref='NonexistentInput' → Success ✓
        Input was never registered
    Impact: Decision nodes reference data that will never exist
    Expected: Should validate input_ref against registered inputs

3. Circular Workflows Allowed (Including Self-Loops)

    What happens: No cycle detection in graph validation
    Test cases:
        Node A → Node B → Node A (circular path) → Success ✓
        Node A → Node A (self-loop) → Success ✓
    Impact: Workflow execution could infinite loop
    Expected: Should detect and reject cycles OR warn user

4. No Graph Connectivity Validation

    What happens: Can create completely disconnected subgraphs
    Test case:
        Workflow has Start → A → End
        Added isolated B → C chain with no connection to main flow
        Both exist in same workflow → Success ✓
    Impact: Dead code; unreachable nodes waste space
    Expected: Could warn about unreachable nodes

5. Multiple Start Nodes

    What happens: Can have 2+ start nodes in same workflow
    Test case: Created 3 start nodes → All accepted ✓
    Impact: Ambiguous workflow entry point
    Expected: Typically workflows have ONE start node

6. Decision Nodes Without Branches

    What happens: Decision nodes can exist without true/false edges
    Test case: Created decision node, no connections → Success ✓
    Impact: Dead-end in workflow; unclear what happens
    Expected: Decision nodes should require 2 outgoing edges (or be validated at "completion" time)

🟠 SECURITY & INJECTION CONCERNS
7. No Label Sanitization

    What happens: Labels accept ANY string content
    Test cases accepted:
        <script>alert('xss')</script>
        <img src=x onerror=alert(1)>
        '; DROP TABLE nodes; --
        ${process.env.SECRET}
        Raw HTML tags
    Impact:
        If labels render as HTML → XSS vulnerability
        If labels used in DB queries → SQL injection risk
        If labels evaluated → Code injection
    Expected: Should sanitize/escape HTML entities at minimum

8. No String Length Limits

    What happens: 500+ character labels accepted
    Test case: Created node with 550-char label → Success ✓
    Impact: UI rendering issues, database bloat, performance
    Expected: Reasonable limits (e.g., 100-200 chars)

🟡 DATA VALIDATION GAPS
9. No Coordinate Bounds

    What happens: x/y can be extreme values
    Test case: Set x=999999, y=-999999 → Success ✓
    Impact: Nodes render off-canvas, unusable UI
    Expected: Reasonable bounds (e.g., -10000 to 10000)

10. Empty/Whitespace Labels

    What happens: Can create nodes with blank labels
    Test cases accepted:
        "" (empty string)
        " " (whitespace only)
        "\n\n" (newlines)
    Impact: Invisible/unusable nodes in UI
    Expected: Require non-empty, trimmed labels

11. Number Input Range: Min > Max

    What happens: Can set min=100, max=10
    Test case: Created input with inverted range → Success ✓
    Impact: Impossible to provide valid value
    Expected: Validate min ≤ max

12. Enum with Empty Array

    What happens: Properly rejected! ✓
    Test case: enum_values=[] → ❌ "Enum inputs must have at least one value"
    Good validation example

🟢 WORKFLOW STRUCTURE ODDITIES
13. Can Delete Start Node

    What happens: No protection for critical nodes
    Test case: Deleted start node → Success ✓
    Impact: Workflow has no entry point
    Expected: Could warn or prevent (though maybe user wants to recreate it)

14. Nodes Without Auto-Positioning Stack

    What happens: If x/y omitted, nodes stack at (0,0)
    Test case: Created 5 nodes without coords → All at origin
    Impact: Users see one node, unaware others exist underneath
    Expected: Auto-layout algorithm (e.g., spread vertically)

15. Decision Nodes Can Be Manually Created (Against Docs)

    What happens: Single add_node for decision works
    Test case: add_node(type='decision', ...) → Success ✓
    Impact: Contradicts tool description saying decisions require batch_edit
    Expected: Either allow single creation OR enforce batch-only

🔵 BATCH OPERATION QUIRKS
16. Batch Atomicity Works (Good!)

    What happens: If any operation fails, all fail
    Test case: Valid ops + invalid op → Nothing applied ✓
    This is CORRECT behavior

17. Field Name Strictness

    What happens: Batch add_connection requires 'from'/'to', not 'from_node_id'/'to_node_id'
    Test case: Used wrong field names → All operations failed
    Impact: Easy mistake, cryptic error
    Expected: Could accept both OR give clearer error

18. Temp ID Pattern Not Enforced

    What happens: Temp IDs work with any pattern (tested temp_123, TEMP_ABC, temp_decision)
    Test case: All accepted ✓
    Impact: None, actually flexible
    Expected: Could document "temp_" prefix is convention, not requirement

🟣 API BEHAVIOR ODDITIES
19. Case Sensitivity Inconsistency

    What happens: Input names are case-insensitive, but node labels might not be
    Test case:
        add_workflow_input(name='Patient Age')
        input_ref='patient age' works ✓
        But finding nodes by label requires exact case?
    Impact: User confusion
    Expected: Document case behavior clearly

20. No "Undo" or Version History

    What happens: Destructive operations are permanent
    Test case: Deleted node → Can't recover
    Impact: User mistakes are costly
    Expected: Maybe a "trash" or version system (though might be out of scope)

📊 SUMMARY BY SEVERITY
Severity 	Count 	Issues
Critical 	6 	Orphaned refs, invalid refs, cycles, disconnected graphs, multi-start, branchless decisions
High 	3 	XSS/injection, no length limits, coordinate bounds
Medium 	5 	Empty labels, inverted ranges, delete start, stacking nodes, decision creation confusion
Low 	6 	Batch field names, temp ID flexibility, case sensitivity, no undo, auto-positioning
🛠️ RECOMMENDED FIXES (Priority Order)

    Input reference validation - Critical for runtime stability
    Cycle detection - Prevent infinite loops
    Label sanitization - Security vulnerability
    String length limits - Prevent abuse
    Range validation (min ≤ max) - Data integrity
    Empty label prevention - UX issue
    Coordinate bounds - UX issue
    Auto-positioning algorithm - UX enhancement
    Workflow completeness checks - Warning system for multi-start, unreachable nodes
    Better error messages - Especially for batch operations
