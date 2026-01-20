import { create } from 'zustand'
import type { Message, ToolCall } from '../types'

interface ChatState {
  // Conversation
  messages: Message[]
  conversationId: string | null

  // Streaming state
  isStreaming: boolean
  streamingContent: string
  currentTaskId: string | null
  cancelledTaskIds: string[]

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

export const useChatStore = create<ChatState>((set, get) => ({
  // Initial state
  messages: [],
  conversationId: null,
  isStreaming: false,
  streamingContent: '',
  currentTaskId: null,
  cancelledTaskIds: [],
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

  setConversationId: (id) => set({ conversationId: id }),

  // Ensure conversationId exists before sync operations
  ensureConversationId: () => {
    const state = get()
    if (!state.conversationId) {
      set({ conversationId: crypto.randomUUID() })
    }
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
    set((state) => ({
      cancelledTaskIds: state.cancelledTaskIds.includes(taskId)
        ? state.cancelledTaskIds
        : [...state.cancelledTaskIds, taskId],
    })),

  isTaskCancelled: (taskId) => get().cancelledTaskIds.includes(taskId),

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
      cancelledTaskIds: [],
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
