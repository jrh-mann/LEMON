# Known Issues & Recent Fixes

## Fixed Issues (2026-02-04)

### 1. Execute Workflow Input Values Not Persisted
**Symptom:** After running a workflow, clicking "Run Again" would reset all input values to defaults instead of keeping the previously entered values.

**Root Cause:** The `ExecuteWorkflowForm` component initialized input values with fresh defaults on every render instead of reading from the tab's persisted `inputValues` storage.

**Fix:** Updated `Modals.tsx` to:
- Read initial values from `activeTab.inputValues` 
- Persist values to tab via `setTabInputValues` on every change
- Persist values before running execution

### 2. Output Template F-Strings Not Working
**Symptom:** Templates like `{BMI}` in output nodes were not outputting variable values correctly, or the interpreter would crash with `KeyError: 'name'`.

**Root Cause:** The `TreeInterpreter` constructor assumed all variables in the `var_list` would have a `name` field. If variables were missing the `name` field (e.g., created via certain code paths), the comprehension `{var['name']: var['id'] for var in var_list}` would fail.

**Fix:** Updated `interpreter.py` to:
- Build `name_to_id` mapping with explicit fallback handling
- Skip variables without `name` fields (they won't be usable in templates by name)
- Also add variable IDs as keys, allowing templates to reference by ID directly (e.g., `{var_bmi_number}`)

---

## Open Issues

needs checklist because forgets vars
voice thing should turn off inbetween





Excellent question! Here's my honest feedback as someone trying to help users build workflows:

What Made This Hard:
1. Image Analysis → Executable Workflow Gap

The analyze_workflow tool gave me a beautiful conceptual understanding (inputs, outputs, decision tree), but no direct path to turn that into executable nodes. I had to:

Manually create 27 nodes one-by-one
Manually create 26 connections
Then realize LATER that none of the decision nodes had conditions
Go back and retrofit all the logic
What Would Help:

An import_from_analysis tool that takes the analyze_workflow session_id and generates:
All nodes with proper types
All connections
Pre-configured decision conditions based on the analysis
Variables already registered
Or at minimum, have analyze_workflow return a "suggested operations" array I could pass directly to batch_edit_workflow
2. Decision Node Condition Confusion

When I created decision nodes initially, I didn't realize conditions were REQUIRED for execution. The tools let me create decision nodes WITHOUT conditions, so I thought they were optional or could be text-based.

What Would Help:

Make condition a required parameter for decision nodes in add_node/batch_edit_workflow (fail fast)
Or have a validation warning: "Decision node created without condition - this will fail at execution"
The system prompt explains conditions well, but I didn't think about it until execution failed
3. No Feedback Loop Between Analysis & Canvas

The analyze_workflow agent gave great predictions, but it was operating on the image, not the actual canvas state. When I asked it to trace through patient scenarios, it couldn't see that the canvas nodes were missing conditions.

What Would Help:

Let analyze_workflow accept a use_canvas=true parameter to analyze the current workflow state instead of the image
Or a compare_analysis_to_canvas tool that validates: "Does the canvas match what was analyzed?"
4. The "Create 3 Patients, Run Both, Compare" Workflow Was Manual

This is actually a GREAT testing pattern, but I had to orchestrate it manually:

Generate patient data
Call analyze_workflow with feedback
Call execute_workflow 3 times
Manually compare results
What Would Help:

A test_workflow tool that:
Takes N test cases (input sets)
Runs execution
Returns pass/fail for each case
Optionally compares against expected outputs
Or a validate_with_test_cases that generates random inputs based on variable types and checks all paths are reachable
5. Batch Operations Are Powerful But Verbose

Creating 27 nodes + 26 connections in batch_edit_workflow would have been a HUGE JSON blob. I opted for individual calls, but then hit the "can't reference new nodes" issue.

What Would Help:

A middle ground: add_node_chain tool for common patterns:
add_node_chain(nodes=[{...}, {...}], connect=true) → creates nodes + auto-connects them in sequence
Or templates: add_decision_with_branches that takes condition + 2 end node labels and creates all 3 nodes + connections atomically
Specific to This Session:
What I Wish Existed:

analyze_workflow() 
→ returns session_id + structured_workflow_json

import_analyzed_workflow(session_id)
→ Creates all nodes, connections, variables, and conditions automatically
→ "Imported 27 nodes and 8 variables from analysis"

validate_workflow()
→ "✓ All decision nodes have conditions"
→ "✓ All paths lead to end nodes"
→ "⚠ Warning: 3 process nodes have no outgoing connections"

test_workflow(test_cases=[...])
→ Runs all test cases
→ "✓ 3/3 test cases passed"
Biggest Pain Points (Ranked):
No way to go from image analysis → executable workflow in one step (had to rebuild manually)
Decision nodes could be created without conditions (silent failure until execution)
No canvas-aware validation (didn't know conditions were missing until I tried to execute)
Testing workflow correctness required manual orchestration (generate data, analyze, execute, compare)
What You're Already Doing Right:
✅ The tools are well-designed and composable
✅ Batch operations with temp IDs are genius
✅ Error messages are clear (helped me debug quickly)
✅ The variable system is elegant once I understood it
✅ The system prompt is comprehensive (though long)

TL;DR: Give me a one-click "import from analysis" button and make conditions required for decision nodes, and this would have been 10x easier! 🚀