import { create } from 'zustand'
import type { Message, ToolCall } from '../types'

interface ChatState {
  // Conversation
  messages: Message[]
  conversationId: string | null

  // Streaming state
  isStreaming: boolean
  streamingContent: string

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
  setMessages: (messages: Message[]) => void

  // Streaming
  setStreaming: (streaming: boolean) => void
  appendStreamContent: (content: string) => void
  clearStreamContent: () => void

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

  setMessages: (messages) => set({ messages }),

  // Streaming
  setStreaming: (streaming) => set({ isStreaming: streaming }),

  appendStreamContent: (content) =>
    set((state) => ({
      streamingContent: state.streamingContent + content,
    })),

  clearStreamContent: () => set({ streamingContent: '' }),

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
