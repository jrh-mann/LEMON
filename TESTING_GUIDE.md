# Workflow Manipulation - Testing Guide

## Implementation Status

✅ **Backend Complete** (59 tests passing)
- Workflow validation
- 7 manipulation tools
- Session state tracking
- Socket event emission

✅ **Frontend Complete**
- Socket event handler added (`workflow_update`)
- TypeScript compilation successful (no errors)
- All store methods in place with undo/redo

---

## Quick Start

### 1. Start Backend
```bash
cd /Users/james/Documents/UCL/year2/SysEng/LEMON
source .venv/bin/activate  # or activate your venv
cd src/backend
python -m uvicorn main:app --reload --port 8000
```

### 2. Start Frontend
```bash
cd /Users/james/Documents/UCL/year2/SysEng/LEMON/src/frontend
npm run dev
```

### 3. Open Browser
- Navigate to `http://localhost:5173` (or the port Vite shows)
- Open DevTools (F12) → Console tab

---

## Testing Checklist

### Test 1: Upload and Analyze Workflow ✓

**Steps**:
1. Click "Upload Image" or drag-drop a workflow image
2. In chat, type: "Analyze this workflow"
3. Wait for analysis to complete

**Expected**:
- ✅ Workflow appears on canvas
- ✅ Console shows: `[Socket] workflow_modified: {action: 'create_workflow', ...}`
- ✅ Canvas switches to "Workflow" tab
- ✅ Nodes are laid out properly

**Console Check**:
```
[Socket] workflow_modified: {action: "create_workflow", data: {...}}
```

---

### Test 2: Add Single Node ✓

**Steps**:
1. After analyzing a workflow, type in chat: "Add a validation step after the first node"
2. Wait for response

**Expected**:
- ✅ New node appears on canvas
- ✅ Console shows: `[Socket] workflow_update: {action: 'add_node', ...}`
- ✅ Console shows: `[Socket] Added node: node_xxxxx`
- ✅ Undo (Ctrl+Z / Cmd+Z) removes the node
- ✅ Redo (Ctrl+Shift+Z / Cmd+Shift+Z) brings it back

**Console Check**:
```
[Socket] workflow_update: {action: "add_node", data: {...}}
[Socket] Added node: node_abc12345
```

**If it fails**:
- Check backend logs for tool execution
- Check if `get_current_workflow` was called first
- Verify node data format in console

---

### Test 3: Modify Node Label ✓

**Steps**:
1. With a workflow on canvas, type: "Change the label of [node name] to 'Data Validation'"
2. Wait for response

**Expected**:
- ✅ Node label updates on canvas
- ✅ Console shows: `[Socket] workflow_update: {action: 'modify_node', ...}`
- ✅ Console shows: `[Socket] Modified node: node_xxxxx`
- ✅ Undo restores old label
- ✅ Redo applies new label

**Console Check**:
```
[Socket] workflow_update: {action: "modify_node", data: {...}}
[Socket] Modified node: node_abc12345
```

---

### Test 4: Delete Node ✓

**Steps**:
1. Type: "Remove the [node name] node"
2. Wait for response

**Expected**:
- ✅ Node disappears from canvas
- ✅ Connected edges also disappear
- ✅ Console shows: `[Socket] workflow_update: {action: 'delete_node', ...}`
- ✅ Console shows: `[Socket] Deleted node: node_xxxxx`
- ✅ Undo brings back node AND edges
- ✅ Redo removes node again

**Console Check**:
```
[Socket] workflow_update: {action: "delete_node", data: {...}}
[Socket] Deleted node: node_abc12345
```

---

### Test 5: Add Connection ✓

**Steps**:
1. Type: "Connect [node A] to [node B]"
2. Wait for response

**Expected**:
- ✅ Edge appears between nodes
- ✅ Console shows: `[Socket] workflow_update: {action: 'add_connection', ...}`
- ✅ Console shows: `[Socket] Added connection: node_xxx -> node_yyy`
- ✅ Undo removes edge
- ✅ Redo adds edge back

**Console Check**:
```
[Socket] workflow_update: {action: "add_connection", data: {...}}
[Socket] Added connection: node_abc -> node_def
```

---

### Test 6: Delete Connection ✓

**Steps**:
1. Type: "Disconnect [node A] from [node B]"
2. Wait for response

**Expected**:
- ✅ Edge disappears
- ✅ Console shows: `[Socket] workflow_update: {action: 'delete_connection', ...}`
- ✅ Console shows: `[Socket] Deleted connection: node_xxx -> node_yyy`
- ✅ Undo brings edge back
- ✅ Redo removes it again

**Console Check**:
```
[Socket] workflow_update: {action: "delete_connection", data: {...}}
[Socket] Deleted connection: node_abc -> node_def
```

---

### Test 7: Batch Edit (Decision Node) ✓

**Steps**:
1. Type: "Add a decision node to check if age >= 18, with separate paths for yes and no"
2. Wait for response

**Expected**:
- ✅ Decision node appears
- ✅ Two branch nodes appear (yes/no or true/false)
- ✅ Three edges appear (input → decision, decision → yes, decision → no)
- ✅ All appear **atomically** (all at once)
- ✅ Console shows: `[Socket] workflow_update: {action: 'batch_edit', ...}`
- ✅ Console shows: `[Socket] Applied batch edit: 6 operations`
- ✅ Undo removes entire structure at once
- ✅ Redo restores entire structure at once

**Console Check**:
```
[Socket] workflow_update: {action: "batch_edit", data: {...}}
[Socket] Applied batch edit: 6 operations
```

**Why This is Important**:
Decision nodes CANNOT be added individually (they need 2 branches to be valid). This tests that batch operations work atomically.

---

### Test 8: Invalid Operation (Error Handling) ✓

**Steps**:
1. Type: "Add a decision node" (without specifying branches)
2. Wait for response

**Expected**:
- ✅ Orchestrator explains it needs branches OR asks for clarification
- ✅ If it tries anyway, backend validation fails
- ✅ Error message appears in chat
- ✅ Workflow remains unchanged
- ✅ NO socket event emitted (because backend validation failed)

**Console Check**:
```
# Should NOT see workflow_update event
# Should see error in chat response
```

**Alternative**: LLM might be smart enough to use batch_edit automatically. In that case, it should succeed!

---

### Test 9: Tab Persistence ✓

**Steps**:
1. Analyze a workflow on Tab 1
2. Add/modify some nodes
3. Create a new tab (Tab 2)
4. Switch back to Tab 1
5. Test undo (Ctrl+Z)

**Expected**:
- ✅ Tab 1 shows all changes made
- ✅ Undo works correctly on Tab 1
- ✅ Undo history is preserved per tab
- ✅ Tab 2 is empty/independent

---

### Test 10: Coordinate Transformation ✓

**Steps**:
1. Add a node via orchestrator
2. Note its position on canvas
3. Manually drag the node
4. Ask orchestrator to move it back

**Expected**:
- ✅ Node appears at correct position (not offset)
- ✅ Moving works smoothly
- ✅ Orchestrator can reposition nodes

**Why This Matters**:
Backend uses top-left coordinates, frontend uses center coordinates. The `transformNodeFromBackend` utility handles this conversion.

---

## Common Issues & Debugging

### Issue: Node appears at wrong position

**Diagnosis**:
```javascript
// In browser console
const store = window.__WORKFLOW_STORE__ || useWorkflowStore.getState()
console.log(store.flowchart.nodes)
```

**Check**: Are x, y values reasonable? (should be > 0, < 2000 typically)

**Fix**: Verify `transformNodeFromBackend` is being called

---

### Issue: Undo doesn't work

**Diagnosis**:
```javascript
// In browser console
const store = useWorkflowStore.getState()
console.log('History length:', store.history.length)
console.log('Current index:', store.historyIndex)
```

**Expected**: history.length > 0, historyIndex >= 0

**Fix**: Verify all store methods call `pushHistory()` (they should already)

---

### Issue: No socket events received

**Diagnosis**:
```javascript
// In browser console, run:
const socket = getSocket()
socket.onAny((event, data) => console.log('ANY EVENT:', event, data))
```

**Check Backend**:
```bash
# In backend logs, look for:
[INFO] tool_response name=add_node data={...}
```

**Fix**:
- Backend might not be emitting events → check `socket_chat.py`
- Frontend might not be listening → check socket connection status

---

### Issue: "Cannot modify non-existent node"

**Console**:
```
[Socket] Cannot modify non-existent node: node_abc123
```

**Cause**: Orchestrator's `current_workflow` state is out of sync with frontend

**Fix**:
1. Refresh page to reset states
2. Verify `publish_latest_analysis` updates orchestrator state
3. Check that socket events are properly updating orchestrator state

---

### Issue: Duplicate edges

**Diagnosis**: Multiple edges between same nodes

**Cause**: `addEdge` duplicate prevention might not be working

**Check**:
```javascript
const store = useWorkflowStore.getState()
const edges = store.flowchart.edges
const duplicates = edges.filter((e, i) =>
  edges.findIndex(e2 => e2.from === e.from && e2.to === e.to) !== i
)
console.log('Duplicates:', duplicates)
```

**Fix**: Already handled in `workflowStore.ts` line 395-398

---

## Advanced Testing

### Stress Test: Multiple Rapid Changes

**Steps**:
1. Type: "Add 5 process nodes in sequence"
2. Wait for all to appear

**Expected**:
- All 5 nodes appear
- Undo removes them in reverse order
- No console errors

---

### Stress Test: Large Batch Operation

**Steps**:
1. Type: "Create a workflow with 3 decision nodes, each with yes/no branches"
2. Wait for completion

**Expected**:
- All 3 decision nodes + 6 branch nodes appear
- ~15+ operations in batch
- Console shows: `Applied batch edit: 15+ operations`

---

### Edge Case: Workflow Reset

**Steps**:
1. Make several changes
2. Type: "Start over with a fresh workflow"
3. Upload new image and analyze

**Expected**:
- Old workflow cleared
- New workflow loaded
- History cleared
- No stale data

---

## Success Criteria

**Minimum Passing**:
- [ ] Tests 1-7 all pass
- [ ] Undo/redo works for all operations
- [ ] No console errors during normal operations
- [ ] Nodes appear at correct positions
- [ ] Edges connect correctly

**Ideal Passing**:
- [ ] All 10 tests pass
- [ ] Tab persistence works
- [ ] Error handling graceful
- [ ] Performance is smooth
- [ ] No TypeScript errors

---

## Performance Monitoring

### Check Render Performance

**In DevTools Console**:
```javascript
// Monitor store updates
const store = useWorkflowStore.getState()
const originalSetFlowchart = store.setFlowchart
store.setFlowchart = (flowchart) => {
  console.time('setFlowchart')
  originalSetFlowchart(flowchart)
  console.timeEnd('setFlowchart')
}
```

**Expected**: < 50ms for most operations

---

## Next Steps After Testing

### If All Tests Pass ✅

1. **Document examples** of successful prompts
2. **Create user guide** with example commands
3. **Consider UI enhancements**:
   - Visual feedback when orchestrator is working
   - Highlight modified nodes briefly
   - Show "Orchestrator is editing..." status

### If Tests Fail ❌

1. **Document the failure** (screenshots, console logs)
2. **Check backend logs** for errors
3. **Verify event data format** matches expectations
4. **Debug store state** using browser DevTools
5. **File issue** with reproduction steps

---

## Useful Console Commands

```javascript
// Get current workflow state
const store = useWorkflowStore.getState()
console.log(store.flowchart)

// Get socket status
const socket = getSocket()
console.log('Connected:', socket?.connected)

// Get undo history
console.log('History:', store.history.length, 'Current:', store.historyIndex)

// Manually trigger undo/redo
store.undo()
store.redo()

// Check what nodes exist
store.flowchart.nodes.forEach(n => console.log(n.id, n.label))

// Check what edges exist
store.flowchart.edges.forEach(e => console.log(e.from, '->', e.to, e.label))
```

---

## Reporting Issues

If you find a bug, please include:

1. **Steps to reproduce** (exact chat messages)
2. **Expected behavior** vs **actual behavior**
3. **Console logs** (screenshot or copy/paste)
4. **Backend logs** (if available)
5. **Workflow state** (from console: `useWorkflowStore.getState().flowchart`)
6. **Socket events** (from console logs with `[Socket]` prefix)

---

## Summary

The implementation is **complete and ready for testing**. The most critical tests are:

1. ✅ Add node (basic functionality)
2. ✅ Batch edit decision node (complex atomic operation)
3. ✅ Undo/redo (history preservation)

If these 3 pass, the system is working correctly. The rest are refinements and edge cases.

**Good luck! 🚀**
