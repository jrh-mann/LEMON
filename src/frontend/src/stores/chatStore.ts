import { create } from 'zustand'
import type { Message, ToolCall } from '../types'
import { useWorkflowStore } from './workflowStore'

interface ChatState {
  // Conversation - NOTE: conversationId is now per-tab, stored in workflowStore
  // This field is kept for backwards compatibility but delegates to workflowStore
  messages: Message[]
  conversationId: string | null  // Mirrors active tab's conversationId

  // Streaming state
  isStreaming: boolean
  streamingContent: string
  currentTaskId: string | null
  cancelledTaskIds: Record<string, number>

  // Processing status (what the orchestrator is currently doing)
  processingStatus: string | null

  // Agent interaction
  pendingQuestion: string | null
  taskId: string | null

  // Pending image for analysis (user uploads, then asks orchestrator to analyse)
  pendingImage: string | null
  pendingImageName: string | null

  // Actions
  addMessage: (message: Message) => void
  updateLastMessage: (content: string) => void
  setConversationId: (id: string | null) => void
  ensureConversationId: () => void
  setMessages: (messages: Message[]) => void

  // Streaming
  setStreaming: (streaming: boolean) => void
  appendStreamContent: (content: string) => void
  clearStreamContent: () => void
  setCurrentTaskId: (taskId: string | null) => void
  clearCurrentTaskId: () => void
  markTaskCancelled: (taskId: string) => void
  isTaskCancelled: (taskId: string) => boolean
  finalizeStreamingMessage: () => void

  // Processing status
  setProcessingStatus: (status: string | null) => void

  // Agent
  setPendingQuestion: (question: string | null, taskId?: string | null) => void
  clearPendingQuestion: () => void

  // Image
  setPendingImage: (image: string | null, name?: string | null) => void
  clearPendingImage: () => void

  // User message helper
  sendUserMessage: (content: string) => Message

  // Reset
  reset: () => void
}

const generateId = () => `msg_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`
const CANCELLED_TASK_TTL_MS = 60_000

const pruneCancelledTaskIds = (ids: Record<string, number>, now: number) => {
  const next: Record<string, number> = {}
  for (const [taskId, timestamp] of Object.entries(ids)) {
    if (now - timestamp < CANCELLED_TASK_TTL_MS) {
      next[taskId] = timestamp
    }
  }
  return next
}

export const useChatStore = create<ChatState>((set, get) => ({
  // Initial state
  messages: [],
  conversationId: null,
  isStreaming: false,
  streamingContent: '',
  currentTaskId: null,
  cancelledTaskIds: {},
  processingStatus: null,
  pendingQuestion: null,
  taskId: null,
  pendingImage: null,
  pendingImageName: null,

  // Actions
  addMessage: (message) =>
    set((state) => ({
      messages: [...state.messages, message],
    })),

  updateLastMessage: (content) =>
    set((state) => {
      const messages = [...state.messages]
      if (messages.length > 0) {
        messages[messages.length - 1] = {
          ...messages[messages.length - 1],
          content,
        }
      }
      return { messages }
    }),

  setConversationId: (id) => {
    set({ conversationId: id })
    // Also update the active tab's conversationId in workflowStore
    if (id) {
      useWorkflowStore.getState().setActiveTabConversationId(id)
    }
  },

  // Ensure conversationId exists before sync operations
  // Uses per-tab conversation ID from workflowStore
  ensureConversationId: () => {
    const workflowStore = useWorkflowStore.getState()
    let conversationId = workflowStore.getActiveTabConversationId()
    if (!conversationId) {
      conversationId = crypto.randomUUID()
      workflowStore.setActiveTabConversationId(conversationId)
    }
    // Sync to chatStore's local state for backwards compatibility
    set({ conversationId })
  },

  setMessages: (messages) => set({ messages }),

  // Streaming
  setStreaming: (streaming) => set({ isStreaming: streaming }),

  appendStreamContent: (content) =>
    set((state) => ({
      streamingContent: state.streamingContent + content,
    })),

  clearStreamContent: () => set({ streamingContent: '' }),

  setCurrentTaskId: (taskId) => set({ currentTaskId: taskId }),

  clearCurrentTaskId: () => set({ currentTaskId: null }),

  markTaskCancelled: (taskId) =>
    set((state) => {
      const now = Date.now()
      const next = pruneCancelledTaskIds(state.cancelledTaskIds, now)
      next[taskId] = now
      return { cancelledTaskIds: next }
    }),

  isTaskCancelled: (taskId) => {
    const now = Date.now()
    const state = get()
    const timestamp = state.cancelledTaskIds[taskId]
    if (!timestamp) {
      return false
    }
    if (now - timestamp >= CANCELLED_TASK_TTL_MS) {
      set({ cancelledTaskIds: pruneCancelledTaskIds(state.cancelledTaskIds, now) })
      return false
    }
    return true
  },

  finalizeStreamingMessage: () => {
    const content = get().streamingContent
    if (content) {
      addAssistantMessage(content)
    }
    set({ streamingContent: '', isStreaming: false, processingStatus: null })
  },

  // Processing status
  setProcessingStatus: (status) => set({ processingStatus: status }),

  // Agent
  setPendingQuestion: (question, taskId = null) =>
    set({ pendingQuestion: question, taskId }),

  clearPendingQuestion: () => set({ pendingQuestion: null, taskId: null }),

  // Image
  setPendingImage: (image, name = null) => set({ pendingImage: image, pendingImageName: name }),
  clearPendingImage: () => set({ pendingImage: null, pendingImageName: null }),

  // User message helper
  sendUserMessage: (content) => {
    const message: Message = {
      id: generateId(),
      role: 'user',
      content,
      timestamp: new Date().toISOString(),
      tool_calls: [],
    }
    get().addMessage(message)
    return message
  },

  // Reset
  reset: () =>
    set({
      messages: [],
      conversationId: null,
      isStreaming: false,
      streamingContent: '',
      currentTaskId: null,
      cancelledTaskIds: {},
      processingStatus: null,
      pendingQuestion: null,
      taskId: null,
      pendingImage: null,
      pendingImageName: null,
    }),
}))

// Helper to add assistant message
export const addAssistantMessage = (
  content: string,
  toolCalls: ToolCall[] = []
): Message => {
  const message: Message = {
    id: generateId(),
    role: 'assistant',
    content,
    timestamp: new Date().toISOString(),
    tool_calls: toolCalls,
  }
  useChatStore.getState().addMessage(message)
  return message
}
