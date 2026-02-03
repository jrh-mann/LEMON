~~different workflows should not share chats~~ FIXED (PR #5)
~~export as png not just json~~ FIXED
~~compile to c~~ FIXED
~~import json not copy paste of text -- also this is broken~~ FIXED

## Structural / Tech Debt

### God-Files (decompose these)
- Canvas.tsx (1,536 lines) — handles panning, dragging, selection, connections, beautification all in one file. Split into Canvas + DragManager + SelectionManager + BeautifyEngine.
- orchestrator_config.py (943 lines) — entire LLM instruction manual embedded in code. Extract prompt into template-based prompt builder loading from text files.
- RightSidebar.tsx (1,088 lines) — properties panel, execution panel, variable management merged. Split into PropertiesPanel + ExecutionPanel.
- orchestrator.py (702 lines) — mixes LLM orchestration with workflow state mutation. Extract state manager.
- workflowStore.ts (664 lines) — manual state management, could benefit from better patterns.

### Redundancy
- inputs vs variables dual naming — translation code scattered across multiple files. Commit to one name everywhere.
- Condition validation repeated 3x — in workflow_validator.py, evaluator.py, and orchestrator_config.py.
- Workflow sync logic appears 3x — in socket_chat.py, orchestrator.py, and conversation store.
- Node color logic defined in 4 places — Canvas.tsx, uiStore.ts, types, CSS.

### Consolidation Opportunities
- Merge socket_chat.py + socket_execution.py into unified socket task runner.
- Merge response_utils.py (87 lines) into common.py.
- Merge tool_summaries.py (78 lines) into orchestrator.
- Group micro-utils (logging.py, paths.py, uploads.py, tokens.py, image.py) by concern.

### Other
- 60+ debug console.log statements in socket.ts need removing.
- Missing user-facing error messages in RightSidebar.
- Socket task state management uses ad-hoc global _TASK_STATE dict.
- MCP dual-mode (direct + MCP) adds complexity — consider committing to one primary mode.

## Evals Needed

### Correctness
- **Image-to-Workflow Fidelity** — Given a hand-drawn flowchart image, does the LLM produce the correct structured workflow? Measure: topology match (nodes/edges), node type accuracy, label accuracy, condition inference. Requires a labeled dataset of 20-50 flowchart images with ground truth JSON.
- **Compiled C vs Python Interpreter Agreement** — Same workflow + same inputs must produce identical output from compiled C and Python TreeInterpreter. Pure automated correctness check, no human labeling needed.
- **Validation Accuracy** — Does the validator catch all structural errors? Build adversarial workflows (cycles, orphan nodes, missing branches) and measure precision/recall.
- **Workflow Roundtrip Fidelity** — Save → load, export JSON → import, export C → compile → run. Output must match at every stage. Catches serialization bugs and key name mismatches.
- **State Sync Consistency** — After N tool calls, is orchestrator state identical to frontend state? Catches pass-by-reference and MCP pass-by-value bugs.

### Performance
- **C vs Python Execution Speed** — Benchmark compiled C against TreeInterpreter across workflow sizes (10, 50, 200 nodes). Quantify the speedup factor.
- **LLM Latency Breakdown** — Per-turn latency split into LLM thinking time, tool execution time, and state sync time. Track per-tool.
- **Execution Engine Throughput** — Workflow executions per second vs workflow complexity.

### LLM Quality
- **Tool Selection Accuracy** — Given 50 natural language instructions (e.g. "add a decision node for age check"), does the orchestrator pick the correct tool(s) with correct arguments?
- **Multi-Turn Coherence** — Over 5-10 message conversations, does the LLM maintain context, reference existing nodes correctly, and avoid re-adding duplicates?
- **Instruction Following** — Precise edits ("move node X below Y", "change label to Z", "delete the false branch") — does it do exactly what was asked, nothing more?