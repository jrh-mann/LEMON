import { create } from 'zustand'
import type { Workflow, WorkflowSummary, Flowchart, FlowNode, FlowEdge, WorkflowAnalysis, ExecutionLogEntry } from '../types'
import type { Annotation } from '../components/ImageAnnotator'
import { patchWorkflow } from '../api/workflows'

// Execution state for visual workflow execution
export interface ExecutionState {
  isExecuting: boolean
  isPaused: boolean
  executionId: string | null
  executingNodeId: string | null
  executedNodeIds: string[]  // Nodes that have been executed (for trail effect)
  executionPath: string[]    // Full path of executed nodes
  executionSpeed: number     // Delay between steps in ms (100-2000)
  executionError: string | null
  executionOutput: any       // Final output of execution
  executionLogs: ExecutionLogEntry[]  // Detailed execution logs for dev tools
  logIndentationStack: string[] // Stack of subworkflow IDs to track indentation depth
}

// Subflow execution state for popup modal visualization
export interface SubflowExecutionState {
  isActive: boolean
  parentNodeId: string | null       // The subprocess node in parent workflow
  subworkflowId: string | null
  subworkflowName: string | null
  nodes: FlowNode[]                 // Subflow nodes for rendering
  edges: FlowEdge[]                 // Subflow edges for rendering
  executingNodeId: string | null    // Currently executing node in subflow
  executedNodeIds: string[]         // Trail of executed nodes in subflow
}

interface WorkflowState {
  // Workflow library
  workflows: WorkflowSummary[]
  isLoadingWorkflows: boolean

  // Current workflow state
  currentWorkflow: Workflow | null
  flowchart: Flowchart
  currentAnalysis: WorkflowAnalysis | null
  conversationId: string | null
  inputValues: Record<string, unknown>

  // Canvas state
  selectedNodeId: string | null
  selectedNodeIds: string[]
  selectedEdge: { from: string; to: string } | null  // Selected edge for editing
  connectMode: boolean
  connectFromId: string | null

  // Execution state for visual workflow execution
  execution: ExecutionState

  // Subflow execution stack for popup modal (supports nested subflows)
  subflowStack: SubflowExecutionState[]

  // History for undo/redo
  history: Flowchart[]
  historyIndex: number

  // Pending image
  pendingImage: string | null
  pendingImageName: string | null
  pendingAnnotations: Annotation[]

  // Actions
  setWorkflows: (workflows: WorkflowSummary[]) => void
  setLoadingWorkflows: (loading: boolean) => void
  setCurrentWorkflow: (workflow: Workflow | null) => void
  setCurrentWorkflowId: (workflowId: string) => void  // Set just the ID (when LLM creates workflow)
  setFlowchart: (flowchart: Flowchart) => void
  setAnalysis: (analysis: WorkflowAnalysis | null) => void
  setConversationId: (conversationId: string | null) => void
  setInputValues: (values: Record<string, unknown>) => void

  // Node operations
  selectNode: (nodeId: string | null) => void
  selectNodes: (nodeIds: string[]) => void
  addToSelection: (nodeId: string) => void
  clearSelection: () => void
  addNode: (node: FlowNode) => void
  updateNode: (nodeId: string, updates: Partial<FlowNode>) => void
  deleteNode: (nodeId: string) => void
  moveNode: (nodeId: string, x: number, y: number) => void
  moveNodes: (nodeIds: string[], dx: number, dy: number) => void

  // Edge operations
  addEdge: (edge: FlowEdge) => void
  updateEdgeLabel: (from: string, to: string, label: string) => void
  swapDecisionEdgeLabels: (decisionNodeId: string) => void
  setDefaultDecisionEdgeLabels: (decisionNodeId: string) => void
  deleteEdge: (from: string, to: string) => void
  deleteEdgeById: (edgeId: string) => void
  selectEdge: (edge: { from: string; to: string } | null) => void

  // Connect mode
  startConnect: (nodeId: string) => void
  cancelConnect: () => void
  completeConnect: (toNodeId: string) => void

  // History
  pushHistory: () => void
  undo: () => void
  redo: () => void
  clearHistory: () => void

  // Pending image
  setPendingImage: (image: string | null, name?: string | null) => void
  clearPendingImage: () => void
  setPendingAnnotations: (annotations: Annotation[]) => void
  clearPendingAnnotations: () => void

  // Reset
  reset: () => void

  // Execution actions
  startExecution: (executionId: string) => void
  pauseExecution: () => void
  resumeExecution: () => void
  stopExecution: () => void
  setExecutingNode: (nodeId: string | null) => void
  markNodeExecuted: (nodeId: string) => void
  setExecutionSpeed: (speed: number) => void
  setExecutionError: (error: string | null) => void
  setExecutionOutput: (output: any) => void
  clearExecution: () => void

  // Subflow execution actions
  startSubflowExecution: (parentNodeId: string, subworkflowId: string, subworkflowName: string, nodes: FlowNode[], edges: FlowEdge[]) => void
  setSubflowExecutingNode: (nodeId: string | null) => void
  markSubflowNodeExecuted: (nodeId: string) => void
  endSubflowExecution: () => void

  // Execution log actions (dev tools)
  addExecutionLog: (log: ExecutionLogEntry) => void
  clearExecutionLogs: () => void
}

const emptyFlowchart: Flowchart = { nodes: [], edges: [] }

// Default execution state
const initialExecutionState: ExecutionState = {
  isExecuting: false,
  isPaused: false,
  executionId: null,
  executingNodeId: null,
  executedNodeIds: [],
  executionPath: [],
  executionSpeed: 500,  // Default 500ms between steps
  executionError: null,
  executionOutput: null,
  executionLogs: [],
  logIndentationStack: [],
}

// Generate unique workflow ID (used for new workflows before they're saved)
// Format matches backend: wf_{uuid hex}
const generateWorkflowId = () => `wf_${crypto.randomUUID().replace(/-/g, '')}`

// Helper to sync edges to backend (fire-and-forget, logs errors)
// This persists UI-triggered edge changes without blocking the UI
const syncEdgesToBackend = async (workflowId: string | undefined, edges: FlowEdge[]) => {
  if (!workflowId) return
  try {
    await patchWorkflow(workflowId, { edges })
    console.log('[WorkflowStore] Synced edges to backend')
  } catch (error) {
    // Log but don't throw - UI updates should not be blocked by backend issues
    console.error('[WorkflowStore] Failed to sync edges to backend:', error)
  }
}

export const useWorkflowStore = create<WorkflowState>((set, get) => ({
  // Initial state
  workflows: [],
  isLoadingWorkflows: false,

  currentWorkflow: {
    id: generateWorkflowId(),
    metadata: { name: 'New Workflow' },
    blocks: [],
    connections: [],
  } as unknown as Workflow,
  flowchart: emptyFlowchart,
  currentAnalysis: null,
  conversationId: null,
  inputValues: {},

  selectedNodeId: null,
  selectedNodeIds: [],
  selectedEdge: null,
  connectMode: false,
  connectFromId: null,
  history: [],
  historyIndex: -1,
  pendingImage: null,
  pendingImageName: null,
  pendingAnnotations: [],

  // Execution state
  execution: { ...initialExecutionState },

  // Subflow execution stack for popup modal (supports nested)
  subflowStack: [],

  // Setters
  setWorkflows: (workflows) => set({ workflows }),
  setLoadingWorkflows: (loading) => set({ isLoadingWorkflows: loading }),
  setCurrentWorkflow: (workflow) => set({ currentWorkflow: workflow }),

  // Sets just the workflow ID for the current workflow
  setCurrentWorkflowId: (workflowId) => set((state) => {
    const workflow = state.currentWorkflow
      ? { ...state.currentWorkflow, id: workflowId }
      : {
        id: workflowId,
        metadata: { name: '' },
        blocks: [],
        connections: [],
      } as unknown as Workflow
    return { currentWorkflow: workflow }
  }),

  setFlowchart: (flowchart) => {
    const state = get()
    state.pushHistory()
    set({ flowchart })
  },

  setAnalysis: (analysis) => set({ currentAnalysis: analysis }),
  setConversationId: (conversationId) => set({ conversationId }),
  setInputValues: (inputValues) => set({ inputValues }),

  // Node operations
  selectNode: (nodeId) => set({
    selectedNodeId: nodeId,
    selectedNodeIds: nodeId ? [nodeId] : [],
    selectedEdge: null  // Clear edge selection when selecting a node
  }),

  selectNodes: (nodeIds) => set({
    selectedNodeId: nodeIds.length > 0 ? nodeIds[0] : null,
    selectedNodeIds: nodeIds,
    selectedEdge: null  // Clear edge selection when selecting nodes
  }),

  addToSelection: (nodeId) => {
    const state = get()
    if (state.selectedNodeIds.includes(nodeId)) return
    set({
      selectedNodeId: nodeId,
      selectedNodeIds: [...state.selectedNodeIds, nodeId],
      selectedEdge: null  // Clear edge selection when selecting nodes
    })
  },

  clearSelection: () => set({
    selectedNodeId: null,
    selectedNodeIds: [],
    selectedEdge: null  // Also clear edge selection
  }),

  addNode: (node) => {
    const state = get()
    state.pushHistory()
    set({
      flowchart: {
        ...state.flowchart,
        nodes: [...state.flowchart.nodes, node],
      },
    })
  },

  updateNode: (nodeId, updates) => {
    const state = get()
    state.pushHistory()
    set({
      flowchart: {
        ...state.flowchart,
        nodes: state.flowchart.nodes.map((node) =>
          node.id === nodeId ? { ...node, ...updates } : node
        ),
      },
    })
  },

  deleteNode: (nodeId) => {
    const state = get()
    state.pushHistory()
    set({
      flowchart: {
        nodes: state.flowchart.nodes.filter((n) => n.id !== nodeId),
        edges: state.flowchart.edges.filter(
          (e) => e.from !== nodeId && e.to !== nodeId
        ),
      },
      selectedNodeId: state.selectedNodeId === nodeId ? null : state.selectedNodeId,
      selectedNodeIds: state.selectedNodeIds.filter(id => id !== nodeId),
    })
  },

  moveNode: (nodeId, x, y) => {
    set((state) => ({
      flowchart: {
        ...state.flowchart,
        nodes: state.flowchart.nodes.map((node) =>
          node.id === nodeId ? { ...node, x, y } : node
        ),
      },
    }))
  },

  moveNodes: (nodeIds: string[], dx: number, dy: number) => {
    const nodeIdSet = new Set(nodeIds)
    set((state) => ({
      flowchart: {
        ...state.flowchart,
        nodes: state.flowchart.nodes.map((node) =>
          nodeIdSet.has(node.id) ? { ...node, x: node.x + dx, y: node.y + dy } : node
        ),
      },
    }))
  },

  // Edge operations
  addEdge: (edge) => {
    const state = get()
    // Prevent duplicates
    const exists = state.flowchart.edges.some(
      (e) => e.from === edge.from && e.to === edge.to
    )
    if (exists) return

    state.pushHistory()
    set({
      flowchart: {
        ...state.flowchart,
        edges: [...state.flowchart.edges, edge],
      },
    })
  },

  deleteEdge: (from, to) => {
    const state = get()
    state.pushHistory()
    set({
      flowchart: {
        ...state.flowchart,
        edges: state.flowchart.edges.filter(
          (e) => !(e.from === from && e.to === to)
        ),
      },
    })
  },

  updateEdgeLabel: (from, to, label) => {
    const state = get()
    const sourceNode = state.flowchart.nodes.find((n) => n.id === from)
    const isDecisionEdge = sourceNode?.type === 'decision'

    state.pushHistory()

    // Compute new edges before setting state (for backend sync)
    let newEdges: FlowEdge[]

    // For decision edges, auto-swap sibling edge labels to maintain true/false pair
    if (isDecisionEdge && (label === 'true' || label === 'false')) {
      const siblingLabel = label === 'true' ? 'false' : 'true'
      newEdges = state.flowchart.edges.map((e) => {
        if (e.from === from && e.to === to) {
          // Update the target edge
          return { ...e, label }
        } else if (e.from === from && e.to !== to) {
          // Auto-swap sibling edge to opposite label
          return { ...e, label: siblingLabel }
        }
        return e
      })
    } else {
      // Non-decision edge or clearing label - just update this edge
      newEdges = state.flowchart.edges.map((e) =>
        e.from === from && e.to === to ? { ...e, label } : e
      )
    }

    // Update local state immediately
    set({
      flowchart: {
        ...state.flowchart,
        edges: newEdges,
      },
    })

    // Sync to backend asynchronously (fire-and-forget)
    const workflowId = state.currentWorkflow?.id
    syncEdgesToBackend(workflowId, newEdges)
  },

  // Swap edge labels for decision nodes (used for batch operations)
  swapDecisionEdgeLabels: (decisionNodeId: string) => {
    const state = get()
    const edgesFromDecision = state.flowchart.edges.filter((e) => e.from === decisionNodeId)
    if (edgesFromDecision.length !== 2) return // Only swap if exactly 2 edges

    state.pushHistory()
    set({
      flowchart: {
        ...state.flowchart,
        edges: state.flowchart.edges.map((e) => {
          if (e.from === decisionNodeId) {
            const currentLabel = e.label?.toLowerCase()
            if (currentLabel === 'true') return { ...e, label: 'false' }
            if (currentLabel === 'false') return { ...e, label: 'true' }
          }
          return e
        }),
      },
    })
  },

  // Set default edge labels for decision nodes based on target node positions
  // Left child = false, Right child = true
  setDefaultDecisionEdgeLabels: (decisionNodeId: string) => {
    const state = get()
    const decisionNode = state.flowchart.nodes.find((n) => n.id === decisionNodeId)
    if (!decisionNode || decisionNode.type !== 'decision') return

    const edgesFromDecision = state.flowchart.edges.filter((e) => e.from === decisionNodeId)
    if (edgesFromDecision.length !== 2) return // Only set defaults if exactly 2 edges

    // Get target nodes and sort by x position (left to right)
    const targetNodes = edgesFromDecision
      .map((e) => ({
        edge: e,
        targetNode: state.flowchart.nodes.find((n) => n.id === e.to),
      }))
      .filter((item) => item.targetNode !== undefined)
      .sort((a, b) => (a.targetNode!.x - b.targetNode!.x))

    if (targetNodes.length !== 2) return

    state.pushHistory()
    set({
      flowchart: {
        ...state.flowchart,
        edges: state.flowchart.edges.map((e) => {
          if (e.from === decisionNodeId) {
            // Left child (smaller x) = false, Right child (larger x) = true
            if (e.to === targetNodes[0].edge.to) return { ...e, label: 'false' }
            if (e.to === targetNodes[1].edge.to) return { ...e, label: 'true' }
          }
          return e
        }),
      },
    })
  },

  deleteEdgeById: (edgeId) => {
    const state = get()
    state.pushHistory()
    set({
      flowchart: {
        ...state.flowchart,
        edges: state.flowchart.edges.filter((e) => e.id !== edgeId),
      },
    })
  },

  selectEdge: (edge) => {
    // Clear node selection when selecting an edge
    set({ selectedEdge: edge, selectedNodeId: null, selectedNodeIds: [] })
  },

  // Connect mode
  startConnect: (nodeId) => set({ connectMode: true, connectFromId: nodeId }),

  cancelConnect: () => set({ connectMode: false, connectFromId: null }),

  completeConnect: (toNodeId) => {
    const state = get()
    if (state.connectFromId && state.connectFromId !== toNodeId) {
      state.addEdge({
        from: state.connectFromId,
        to: toNodeId,
        label: '',
      })
    }
    set({ connectMode: false, connectFromId: null })
  },

  // History
  pushHistory: () => {
    const state = get()
    const newHistory = state.history.slice(0, state.historyIndex + 1)
    newHistory.push(structuredClone(state.flowchart))
    // Limit history size
    if (newHistory.length > 50) newHistory.shift()
    set({ history: newHistory, historyIndex: newHistory.length - 1 })
  },

  undo: () => {
    const state = get()
    if (state.historyIndex > 0) {
      const newIndex = state.historyIndex - 1
      set({
        flowchart: structuredClone(state.history[newIndex]),
        historyIndex: newIndex,
      })
    }
  },

  redo: () => {
    const state = get()
    if (state.historyIndex < state.history.length - 1) {
      const newIndex = state.historyIndex + 1
      set({
        flowchart: structuredClone(state.history[newIndex]),
        historyIndex: newIndex,
      })
    }
  },

  clearHistory: () => set({ history: [], historyIndex: -1 }),

  // Pending image
  setPendingImage: (image, name = null) => set({ pendingImage: image, pendingImageName: name, pendingAnnotations: [] }),
  clearPendingImage: () => set({ pendingImage: null, pendingImageName: null, pendingAnnotations: [] }),
  setPendingAnnotations: (annotations) => set({ pendingAnnotations: annotations }),
  clearPendingAnnotations: () => set({ pendingAnnotations: [] }),

  // Reset
  reset: () =>
    set({
      currentWorkflow: {
        id: generateWorkflowId(),
        metadata: { name: 'New Workflow' },
        blocks: [],
        connections: [],
      } as unknown as Workflow,
      flowchart: emptyFlowchart,
      currentAnalysis: null,
      conversationId: null,
      inputValues: {},
      selectedNodeId: null,
      selectedNodeIds: [],
      connectMode: false,
      connectFromId: null,
      history: [],
      historyIndex: -1,
      pendingImage: null,
      pendingImageName: null,
      pendingAnnotations: [],
      execution: { ...initialExecutionState },
    }),

  // Execution actions
  // Starts a new execution session with the given ID
  startExecution: (executionId: string) => set((state) => ({
    execution: {
      ...state.execution,
      isExecuting: true,
      isPaused: false,
      executionId,
      executingNodeId: null,
      executedNodeIds: [],
      executionPath: [],
      executionError: null,
      executionOutput: null,
      logIndentationStack: [],
    },
  })),

  // Pauses the current execution
  pauseExecution: () => set((state) => ({
    execution: {
      ...state.execution,
      isPaused: true,
    },
  })),

  // Resumes a paused execution
  resumeExecution: () => set((state) => ({
    execution: {
      ...state.execution,
      isPaused: false,
    },
  })),

  // Stops the current execution and clears executing state (keeps executed trail)
  stopExecution: () => set((state) => ({
    execution: {
      ...state.execution,
      isExecuting: false,
      isPaused: false,
      executingNodeId: null,
    },
  })),

  // Sets the currently executing node (highlights it)
  setExecutingNode: (nodeId: string | null) => set((state) => ({
    execution: {
      ...state.execution,
      executingNodeId: nodeId,
    },
  })),

  // Marks a node as executed (adds to trail)
  markNodeExecuted: (nodeId: string) => set((state) => ({
    execution: {
      ...state.execution,
      executedNodeIds: state.execution.executedNodeIds.includes(nodeId)
        ? state.execution.executedNodeIds
        : [...state.execution.executedNodeIds, nodeId],
      executionPath: [...state.execution.executionPath, nodeId],
    },
  })),

  // Sets the execution speed (delay between steps in ms)
  setExecutionSpeed: (speed: number) => set((state) => ({
    execution: {
      ...state.execution,
      executionSpeed: Math.max(100, Math.min(2000, speed)),  // Clamp to 100-2000ms
    },
  })),

  // Sets an execution error
  setExecutionError: (error: string | null) => set((state) => ({
    execution: {
      ...state.execution,
      executionError: error,
      isExecuting: error ? false : state.execution.isExecuting,
    },
  })),

  // Sets the final execution output
  setExecutionOutput: (output: any) => set((state) => ({
    execution: {
      ...state.execution,
      executionOutput: output,
    },
  })),

  // Clears all execution state (resets to initial)
  clearExecution: () => set({
    execution: { ...initialExecutionState },
    subflowStack: [],  // Also clear subflow stack
  }),

  // Subflow execution actions for popup modal visualization (stack-based)
  startSubflowExecution: (parentNodeId, subworkflowId, subworkflowName, nodes, edges) => set((state) => ({
    subflowStack: [
      ...state.subflowStack,
      {
        isActive: true,
        parentNodeId,
        subworkflowId,
        subworkflowName,
        nodes,
        edges,
        executingNodeId: null,
        executedNodeIds: [],
      }
    ],
  })),

  setSubflowExecutingNode: (nodeId) => set((state) => {
    if (state.subflowStack.length === 0) return state
    const newStack = [...state.subflowStack]
    newStack[newStack.length - 1] = {
      ...newStack[newStack.length - 1],
      executingNodeId: nodeId,
    }
    return { subflowStack: newStack }
  }),

  markSubflowNodeExecuted: (nodeId) => set((state) => {
    if (state.subflowStack.length === 0) return state
    const topSubflow = state.subflowStack[state.subflowStack.length - 1]
    if (topSubflow.executedNodeIds.includes(nodeId)) return state
    const newStack = [...state.subflowStack]
    newStack[newStack.length - 1] = {
      ...topSubflow,
      executedNodeIds: [...topSubflow.executedNodeIds, nodeId],
    }
    return { subflowStack: newStack }
  }),

  endSubflowExecution: () => set((state) => ({
    subflowStack: state.subflowStack.slice(0, -1),  // Pop top subflow
  })),

  // Execution log actions (dev tools)
  addExecutionLog: (log) => set((state) => {
    let currentStack = state.execution.logIndentationStack || [];
    let entryStack: string[] = [];

    if (log.log_type === 'subflow_start') {
      // For start event, use parent stack for entry, then push
      entryStack = [...currentStack];
      // Only push if subworkflow_id is present
      if (log.subworkflow_id) {
        currentStack = [...currentStack, log.subworkflow_id];
      }
    } else if (log.log_type === 'subflow_complete') {
      // For complete event, pop logic (return to parent level)
      if (currentStack.length > 0) {
        currentStack = currentStack.slice(0, -1);
      }
      entryStack = [...currentStack];
    } else {
      // For normal nodes, use current stack
      entryStack = [...currentStack];
    }

    // Force override the stack with our client-side computed stack
    // This ensures consistent indentation even if backend is stale/flaky
    const newLog = { ...log, subworkflow_stack: entryStack };

    return {
      execution: {
        ...state.execution,
        logIndentationStack: currentStack,
        executionLogs: [...state.execution.executionLogs, newLog],
      },
    };
  }),

  clearExecutionLogs: () => set((state) => ({
    execution: {
      ...state.execution,
      executionLogs: [],
    },
  })),
}))
