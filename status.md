# Project Status
*Last updated: 04:25:34*

---

## Team

🟢 **james**: Fix preloaded workflows showing overlapping nodes
   - *Adding auto-layout to transform function and updating WorkflowBrowser to use it*
🟢 **Jeet**: Fix project_summary 500 error in coordination server
   - *Locate project_summary handler and update sqlite Row access (likely .get) to safe index/key access; add small test or guard*
🟢 **jude**: Fix flowchart image parsing and allow unlimited connections per node
   - *1. Find and fix the image-to-flowchart parsing logic 2. Update getAvailablePorts to always show all 4 ports*

## Messages

**James** → everyone (03:16:26)
> ✅ COMPLETED: Fixed all 6 workflow rendering bugs

Changes made:
1. **web/src/utils/canvas.ts** - Added `transformFlowchartFromBackend()` and `transformNodeFromBackend()` functions that:
   - Convert TOP-LEFT coordinates to CENTER coordinates
   - Map BlockType to FlowNodeType ('input'→'process', 'output'→'end', 'workflow_ref'→'subprocess')
   - Sanitize JSON artifacts from labels

2. **web/src/api/socket.ts** - Updated `agent_complete` and `workflow_modified` handlers to transform backend data before setting flowchart state

3. **src/lemon/agent/tools.py** - Replaced naive vertical stacking with proper DAG layout:
   - BFS-based level assignment (propagates levels based on graph edges)
   - Groups nodes by level
   - Sorts nodes within levels to minimize edge crossings
   - Centers each level horizontally

The frontend build passes. Workflows should now render with proper structure instead of single columns.

@Jude - The coordinate system is now fixed. Your drag-to-connect should work correctly with center-based coordinates!

**James** → Jude (03:13:27)
> Hey Jude - I need to fix critical rendering bugs in Canvas.tsx. The coordinate system is broken (backend sends top-left, frontend expects center). This will affect your drag-to-connect work since connection points need the coordinate fix. I'll try to make changes compatible with your work. Let me know if you need me to wait or coordinate on specific parts!

**James** → everyone (03:13:17)
> 🚨 CRITICAL BUG REPORT - Workflow Rendering Issues 🚨

I've identified 6 critical bugs causing the new frontend to catastrophically break when rendering workflows:

**1. COORDINATE SYSTEM MISMATCH**
- Backend sends (x,y) as TOP-LEFT corner
- Frontend Canvas.tsx expects (x,y) as CENTER
- Result: All nodes render offset, edges don't connect properly

**2. NODE TYPE MISMATCH**
- GetCurrentWorkflowTool returns BlockType: 'input' | 'decision' | 'output' | 'workflow_ref'
- Frontend expects FlowNodeType: 'start' | 'process' | 'decision' | 'subprocess' | 'end'
- Result: Nodes don't render correctly

**3. BROKEN AUTO-LAYOUT (CreateWorkflowTool)**
- Current: Naive vertical stack at x=400
- Old frontend: Proper DAG layout with BFS leveling
- Result: All nodes in single column instead of proper flowchart structure

**4. EDGE PATH CALCULATION**
- getConnectionPoint() assumes center coordinates
- With top-left coords, all edges connect to wrong points

**5. VIEWBOX CALCULATION**
- calculateViewBox() adds margins around center-based bounds
- Wrong with top-left coordinates

**6. LABEL SANITIZATION**
- JSON strings not properly cleaned for display in node labels

I'm fixing all of these now. Heads up to Jude working on drag-to-connect - the coordinate system fix may affect your work!

**Jeet** → Jude (03:06:08)
> Hi Jude!

## Recent Changes

- **[MODIFIED]** Fixed flowchart parsing and unlimited node connections
  - *Nodes now always show all 4 connection ports. Flowchart parsing improved with better label sanitization and fallback connections.*
- **[MODIFIED]** Hardened project_summary/status/team-awareness endpoints to tolerate missing columns by adding safe column selection and row access helpers; updated summary building to use safe getters.
  - *Project summary endpoints should no longer 500 when optional columns are missing or NULL in older DBs.*
- **[FIXED]** Fixed preloaded workflows showing overlapping nodes by adding auto-layout detection and DAG layout algorithm to frontend
  - *Workflows loaded from the browser now automatically get proper DAG layout when their positions are all at (0,0) or overlapping*
- **[FIXED]** Fixed 6 critical workflow rendering bugs: coordinate transform (top-left→center), node type mapping (BlockType→FlowNodeType), DAG auto-layout algorithm, edge paths, viewBox, and label sanitization
  - *Workflows now render correctly with proper DAG layout, nodes positioned in levels based on graph structure, edges connect properly, and JSON artifacts are sanitized from labels*
- **[MODIFIED]** Fixed 6 critical workflow rendering bugs: coordinate transform (top-left→center), node type mapping (BlockType→FlowNodeType), DAG auto-layout algorithm, edge paths, viewBox, and label sanitization
  - *Workflows now render correctly with proper DAG layout, nodes positioned in levels based on graph structure, edges connect properly, and JSON artifacts are sanitized from labels*
- **[MODIFIED]** Added drag-to-connect handles on node edges with smart positioning
  - *Users can now hover over nodes to see connection ports and drag from them to create edges. Ports only appear on sides without existing connections.*
- **[MODIFIED]** Fixed project_summary to handle sqlite rows when checking vision so the endpoint stops 500ing.
  - *Project summary endpoint no longer crashes when online agents exist.*
- **[MODIFIED]** Fixed project_summary to handle sqlite rows when checking vision so the endpoint stops 500ing.
  - *Project summary endpoint no longer crashes when online agents exist.*

---
*This file auto-updates. Keep it open to see live status.*