import { create } from 'zustand'
import type { Workflow, WorkflowSummary, Flowchart, FlowNode, FlowEdge } from '../types'

// Tab interface
export interface WorkflowTab {
  id: string
  title: string
  workflow: Workflow | null
  flowchart: Flowchart
  history: Flowchart[]
  historyIndex: number
  pendingImage: string | null
  pendingImageName: string | null
}

interface WorkflowState {
  // Workflow library
  workflows: WorkflowSummary[]
  isLoadingWorkflows: boolean

  // Tabs
  tabs: WorkflowTab[]
  activeTabId: string

  // Current workflow (derived from active tab)
  currentWorkflow: Workflow | null
  flowchart: Flowchart

  // Canvas state
  selectedNodeId: string | null
  selectedNodeIds: string[]
  connectMode: boolean
  connectFromId: string | null

  // History for undo/redo (derived from active tab)
  history: Flowchart[]
  historyIndex: number

  // Pending image (per-tab)
  pendingImage: string | null
  pendingImageName: string | null

  // Actions
  setWorkflows: (workflows: WorkflowSummary[]) => void
  setLoadingWorkflows: (loading: boolean) => void
  setCurrentWorkflow: (workflow: Workflow | null) => void
  setFlowchart: (flowchart: Flowchart) => void

  // Tab operations
  addTab: (title?: string, workflow?: Workflow | null, flowchart?: Flowchart) => string
  closeTab: (tabId: string) => void
  switchTab: (tabId: string) => void
  updateTabTitle: (tabId: string, title: string) => void

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

  // Pending image (per-tab)
  setPendingImage: (image: string | null, name?: string | null) => void
  clearPendingImage: () => void

  // Reset
  reset: () => void
}

const emptyFlowchart: Flowchart = { nodes: [], edges: [] }

// Generate unique tab ID
const generateTabId = () => `tab_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`

// Create initial tab
const createInitialTab = (): WorkflowTab => ({
  id: generateTabId(),
  title: 'New Workflow',
  workflow: null,
  flowchart: emptyFlowchart,
  history: [],
  historyIndex: -1,
  pendingImage: null,
  pendingImageName: null,
})

const initialTab = createInitialTab()

export const useWorkflowStore = create<WorkflowState>((set, get) => ({
  // Initial state
  workflows: [],
  isLoadingWorkflows: false,

  // Tabs
  tabs: [initialTab],
  activeTabId: initialTab.id,

  // Current state (from active tab)
  currentWorkflow: null,
  flowchart: emptyFlowchart,
  selectedNodeId: null,
  selectedNodeIds: [],
  connectMode: false,
  connectFromId: null,
  history: [],
  historyIndex: -1,
  pendingImage: null,
  pendingImageName: null,

  // Setters
  setWorkflows: (workflows) => set({ workflows }),
  setLoadingWorkflows: (loading) => set({ isLoadingWorkflows: loading }),
  setCurrentWorkflow: (workflow) => {
    const state = get()
    const tabs = state.tabs.map(tab =>
      tab.id === state.activeTabId
        ? { ...tab, workflow, title: workflow?.metadata?.name || tab.title }
        : tab
    )
    set({ currentWorkflow: workflow, tabs })
  },
  setFlowchart: (flowchart) => {
    const state = get()
    state.pushHistory()
    const tabs = state.tabs.map(tab =>
      tab.id === state.activeTabId
        ? { ...tab, flowchart }
        : tab
    )
    set({ flowchart, tabs })
  },

  // Tab operations
  addTab: (title = 'New Workflow', workflow = null, flowchart = emptyFlowchart) => {
    const newTab: WorkflowTab = {
      id: generateTabId(),
      title,
      workflow,
      flowchart,
      history: [],
      historyIndex: -1,
      pendingImage: null,
      pendingImageName: null,
    }
    // Save current tab's pending image before switching
    const state = get()
    const tabs = state.tabs.map(tab =>
      tab.id === state.activeTabId
        ? { ...tab, pendingImage: state.pendingImage, pendingImageName: state.pendingImageName }
        : tab
    )
    set({
      tabs: [...tabs, newTab],
      activeTabId: newTab.id,
      currentWorkflow: workflow,
      flowchart,
      selectedNodeId: null,
      selectedNodeIds: [],
      connectMode: false,
      connectFromId: null,
      history: [],
      historyIndex: -1,
      pendingImage: null,
      pendingImageName: null,
    })
    return newTab.id
  },

  closeTab: (tabId) => {
    const state = get()
    if (state.tabs.length <= 1) {
      // Don't close last tab, just reset it
      const newTab = createInitialTab()
      set({
        tabs: [newTab],
        activeTabId: newTab.id,
        currentWorkflow: null,
        flowchart: emptyFlowchart,
        selectedNodeId: null,
        selectedNodeIds: [],
        history: [],
        historyIndex: -1,
        pendingImage: null,
        pendingImageName: null,
      })
      return
    }

    const tabIndex = state.tabs.findIndex(t => t.id === tabId)
    const newTabs = state.tabs.filter(t => t.id !== tabId)

    // If closing active tab, switch to adjacent tab
    let newActiveId = state.activeTabId
    if (tabId === state.activeTabId) {
      const newIndex = Math.min(tabIndex, newTabs.length - 1)
      newActiveId = newTabs[newIndex].id
    }

    const activeTab = newTabs.find(t => t.id === newActiveId)!
    set({
      tabs: newTabs,
      activeTabId: newActiveId,
      currentWorkflow: activeTab.workflow,
      flowchart: activeTab.flowchart,
      history: activeTab.history,
      historyIndex: activeTab.historyIndex,
      selectedNodeId: null,
      selectedNodeIds: [],
      pendingImage: activeTab.pendingImage,
      pendingImageName: activeTab.pendingImageName,
    })
  },

  switchTab: (tabId) => {
    const state = get()
    if (tabId === state.activeTabId) return

    // Save current tab state including pending image
    const tabs = state.tabs.map(tab =>
      tab.id === state.activeTabId
        ? {
            ...tab,
            flowchart: state.flowchart,
            history: state.history,
            historyIndex: state.historyIndex,
            pendingImage: state.pendingImage,
            pendingImageName: state.pendingImageName,
          }
        : tab
    )

    const newTab = tabs.find(t => t.id === tabId)
    if (!newTab) return

    set({
      tabs,
      activeTabId: tabId,
      currentWorkflow: newTab.workflow,
      flowchart: newTab.flowchart,
      history: newTab.history,
      historyIndex: newTab.historyIndex,
      selectedNodeId: null,
      selectedNodeIds: [],
      connectMode: false,
      connectFromId: null,
      pendingImage: newTab.pendingImage,
      pendingImageName: newTab.pendingImageName,
    })
  },

  updateTabTitle: (tabId, title) => {
    set(state => ({
      tabs: state.tabs.map(tab =>
        tab.id === tabId ? { ...tab, title } : tab
      ),
    }))
  },

  // Node operations
  selectNode: (nodeId) => set({
    selectedNodeId: nodeId,
    selectedNodeIds: nodeId ? [nodeId] : []
  }),

  selectNodes: (nodeIds) => set({
    selectedNodeId: nodeIds.length > 0 ? nodeIds[0] : null,
    selectedNodeIds: nodeIds
  }),

  addToSelection: (nodeId) => {
    const state = get()
    if (state.selectedNodeIds.includes(nodeId)) return
    set({
      selectedNodeId: nodeId,
      selectedNodeIds: [...state.selectedNodeIds, nodeId]
    })
  },

  clearSelection: () => set({
    selectedNodeId: null,
    selectedNodeIds: []
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

  // Pending image (per-tab)
  setPendingImage: (image, name = null) => set({ pendingImage: image, pendingImageName: name }),
  clearPendingImage: () => set({ pendingImage: null, pendingImageName: null }),

  // Reset
  reset: () =>
    set({
      currentWorkflow: null,
      flowchart: emptyFlowchart,
      selectedNodeId: null,
      selectedNodeIds: [],
      connectMode: false,
      connectFromId: null,
      history: [],
      historyIndex: -1,
      pendingImage: null,
      pendingImageName: null,
    }),
}))
