import { create } from 'zustand'
import type { Stage, ModalType, SidebarTab, ToolCall } from '../types'

export type CanvasTab = 'workflow' | 'image'

// Canvas interaction mode: 'select' for box selection, 'pan' for viewport dragging
export type CanvasMode = 'select' | 'pan'

interface UIState {
  // App stage
  stage: Stage

  // Modal state
  modalOpen: ModalType

  // Sidebar
  activeTab: SidebarTab

  // Canvas tab (workflow vs source image)
  canvasTab: CanvasTab

  // Canvas interaction mode (select vs pan)
  canvasMode: CanvasMode

  // Loading/error
  isLoading: boolean
  loadingMessage: string | null
  error: string | null

  // Canvas zoom
  zoom: number
  panX: number
  panY: number

  // Chat panel height (for dynamic workspace sizing)
  chatHeight: number

  // Developer mode
  devMode: boolean
  selectedToolCall: ToolCall | null  // For tool inspector modal

  // Execution tracking
  trackExecution: boolean  // Auto-pan to follow executing node

  // Execution log modal (dev tools)
  executionLogModalOpen: boolean

  // Workspace reveal (home -> workflow transition)
  workspaceRevealed: boolean

  // Actions
  setStage: (stage: Stage) => void
  openModal: (modal: ModalType) => void
  closeModal: () => void
  setActiveTab: (tab: SidebarTab) => void
  setCanvasTab: (tab: CanvasTab) => void
  setCanvasMode: (mode: CanvasMode) => void
  toggleCanvasMode: () => void
  setLoading: (loading: boolean, message?: string | null) => void
  setError: (error: string | null) => void
  clearError: () => void

  // Canvas
  setZoom: (zoom: number) => void
  zoomIn: () => void
  zoomOut: () => void
  resetZoom: () => void
  setPan: (x: number, y: number) => void

  // Chat
  setChatHeight: (height: number) => void

  // Dev mode
  setDevMode: (enabled: boolean) => void
  toggleDevMode: () => void
  setSelectedToolCall: (toolCall: ToolCall | null) => void

  // Execution tracking
  setTrackExecution: (enabled: boolean) => void

  // Execution log modal
  setExecutionLogModalOpen: (open: boolean) => void

  // Workspace reveal
  revealWorkspace: () => void

  // Reset
  reset: () => void
}

const MIN_ZOOM = 0.25
const MAX_ZOOM = 8
const ZOOM_STEP = 0.7

export const useUIStore = create<UIState>((set) => ({
  // Initial state
  stage: 'idle',
  modalOpen: 'none',
  activeTab: 'library',
  canvasTab: 'workflow',
  canvasMode: 'select',
  isLoading: false,
  loadingMessage: null,
  error: null,
  zoom: 1,
  panX: 0,
  panY: 0,
  chatHeight: 280,
  devMode: typeof localStorage !== 'undefined' && localStorage.getItem('devMode') === 'true',
  selectedToolCall: null,
  trackExecution: typeof localStorage !== 'undefined' && localStorage.getItem('trackExecution') !== 'false',  // Default on
  executionLogModalOpen: false,
  workspaceRevealed: false,

  // Actions
  setStage: (stage) => set({ stage }),

  openModal: (modal) => set({ modalOpen: modal }),

  closeModal: () => set({ modalOpen: 'none' }),

  setActiveTab: (tab) => set({ activeTab: tab }),

  setCanvasTab: (tab) => set({ canvasTab: tab }),

  setCanvasMode: (mode) => set({ canvasMode: mode }),

  toggleCanvasMode: () =>
    set((state) => ({
      canvasMode: state.canvasMode === 'select' ? 'pan' : 'select',
    })),

  setLoading: (loading, message = null) =>
    set({ isLoading: loading, loadingMessage: message }),

  setError: (error) => set({ error }),

  clearError: () => set({ error: null }),

  // Canvas
  setZoom: (zoom) =>
    set({ zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom)) }),

  zoomIn: () =>
    set((state) => ({
      zoom: Math.min(MAX_ZOOM, state.zoom + ZOOM_STEP),
    })),

  zoomOut: () =>
    set((state) => ({
      zoom: Math.max(MIN_ZOOM, state.zoom - ZOOM_STEP),
    })),

  resetZoom: () => set({ zoom: 1, panX: 0, panY: 0 }),

  setPan: (x, y) => set({ panX: x, panY: y }),

  // Chat
  setChatHeight: (height) => set({ chatHeight: height }),

  // Dev mode
  setDevMode: (enabled) => {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem('devMode', String(enabled))
    }
    set({ devMode: enabled })
  },

  toggleDevMode: () => set((state) => {
    const newValue = !state.devMode
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem('devMode', String(newValue))
    }
    return { devMode: newValue }
  }),

  setSelectedToolCall: (toolCall) => set({ selectedToolCall: toolCall }),

  // Execution tracking
  setTrackExecution: (enabled) => {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem('trackExecution', String(enabled))
    }
    set({ trackExecution: enabled })
  },

  // Execution log modal
  setExecutionLogModalOpen: (open) => set({ executionLogModalOpen: open }),

  // Workspace reveal
  revealWorkspace: () => set({ workspaceRevealed: true }),

  // Reset
  reset: () =>
    set({
      stage: 'idle',
      modalOpen: 'none',
      activeTab: 'library',
      canvasTab: 'workflow',
      canvasMode: 'select',
      isLoading: false,
      loadingMessage: null,
      error: null,
      zoom: 1,
      panX: 0,
      panY: 0,
      chatHeight: 280,
      workspaceRevealed: false,
    }),
}))
