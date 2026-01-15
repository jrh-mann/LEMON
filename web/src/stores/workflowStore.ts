import { create } from 'zustand'
import type { Workflow, WorkflowSummary, Flowchart, FlowNode, FlowEdge } from '../types'

interface WorkflowState {
  // Workflow library
  workflows: WorkflowSummary[]
  isLoadingWorkflows: boolean

  // Current workflow
  currentWorkflow: Workflow | null
  flowchart: Flowchart

  // Canvas state
  selectedNodeId: string | null
  connectMode: boolean
  connectFromId: string | null

  // History for undo/redo
  history: Flowchart[]
  historyIndex: number

  // Actions
  setWorkflows: (workflows: WorkflowSummary[]) => void
  setLoadingWorkflows: (loading: boolean) => void
  setCurrentWorkflow: (workflow: Workflow | null) => void
  setFlowchart: (flowchart: Flowchart) => void

  // Node operations
  selectNode: (nodeId: string | null) => void
  addNode: (node: FlowNode) => void
  updateNode: (nodeId: string, updates: Partial<FlowNode>) => void
  deleteNode: (nodeId: string) => void
  moveNode: (nodeId: string, x: number, y: number) => void

  // Edge operations
  addEdge: (edge: FlowEdge) => void
  deleteEdge: (from: string, to: string) => void
  deleteEdgeById: (edgeId: string) => void

  // Connect mode
  startConnect: (nodeId: string) => void
  cancelConnect: () => void
  completeConnect: (toNodeId: string) => void

  // History
  pushHistory: () => void
  undo: () => void
  redo: () => void
  clearHistory: () => void

  // Reset
  reset: () => void
}

const emptyFlowchart: Flowchart = { nodes: [], edges: [] }

export const useWorkflowStore = create<WorkflowState>((set, get) => ({
  // Initial state
  workflows: [],
  isLoadingWorkflows: false,
  currentWorkflow: null,
  flowchart: emptyFlowchart,
  selectedNodeId: null,
  connectMode: false,
  connectFromId: null,
  history: [],
  historyIndex: -1,

  // Setters
  setWorkflows: (workflows) => set({ workflows }),
  setLoadingWorkflows: (loading) => set({ isLoadingWorkflows: loading }),
  setCurrentWorkflow: (workflow) => set({ currentWorkflow: workflow }),
  setFlowchart: (flowchart) => {
    const state = get()
    state.pushHistory()
    set({ flowchart })
  },

  // Node operations
  selectNode: (nodeId) => set({ selectedNodeId: nodeId }),

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

  // Reset
  reset: () =>
    set({
      currentWorkflow: null,
      flowchart: emptyFlowchart,
      selectedNodeId: null,
      connectMode: false,
      connectFromId: null,
      history: [],
      historyIndex: -1,
    }),
}))
