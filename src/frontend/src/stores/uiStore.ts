import { create } from 'zustand'
import type { Stage, ModalType, SidebarTab } from '../types'

export type CanvasTab = 'workflow' | 'image'

interface UIState {
  // App stage
  stage: Stage

  // Modal state
  modalOpen: ModalType

  // Sidebar
  activeTab: SidebarTab

  // Canvas tab (workflow vs source image)
  canvasTab: CanvasTab

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

  // Actions
  setStage: (stage: Stage) => void
  openModal: (modal: ModalType) => void
  closeModal: () => void
  setActiveTab: (tab: SidebarTab) => void
  setCanvasTab: (tab: CanvasTab) => void
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
  isLoading: false,
  loadingMessage: null,
  error: null,
  zoom: 1,
  panX: 0,
  panY: 0,
  chatHeight: 280,

  // Actions
  setStage: (stage) => set({ stage }),

  openModal: (modal) => set({ modalOpen: modal }),

  closeModal: () => set({ modalOpen: 'none' }),

  setActiveTab: (tab) => set({ activeTab: tab }),

  setCanvasTab: (tab) => set({ canvasTab: tab }),

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

  // Reset
  reset: () =>
    set({
      stage: 'idle',
      modalOpen: 'none',
      activeTab: 'library',
      canvasTab: 'workflow',
      isLoading: false,
      loadingMessage: null,
      error: null,
      zoom: 1,
      panX: 0,
      panY: 0,
      chatHeight: 280,
    }),
}))
