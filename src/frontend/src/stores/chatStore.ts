import { create } from 'zustand'
import type { Message, ToolCall } from '../types'
import { useWorkflowStore } from './workflowStore'

// Shape of a single inline question from the ask_question tool
type PendingQuestion = { question: string; options: { label: string; value: string }[] }

interface ChatState {
  // Conversation — conversationId is per-tab in workflowStore, mirrored here for socket operations
  messages: Message[]
  conversationId: string | null

  // Streaming state
  isStreaming: boolean
  streamingContent: string
  currentTaskId: string | null
  cancelledTaskIds: Record<string, number>

  // Processing status (what the orchestrator is currently doing)
  processingStatus: string | null

  // Live reasoning stream from LLM extended thinking
  thinkingContent: string

  // Queue of inline questions from ask_question tool (rendered as cards with option chips).
  // Multiple questions are queued and shown one at a time — answering one reveals the next.
  pendingQuestions: PendingQuestion[]

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

  // Thinking stream
  appendThinkingContent: (content: string) => void
  clearThinkingContent: () => void

  // Inline question queue — enqueue pushes, clearPendingQuestion pops the front
  enqueuePendingQuestion: (question: PendingQuestion) => void
  clearPendingQuestion: () => void

  // User message helper
  sendUserMessage: (content: string) => Message

  // Snapshot: save/restore chat state when switching workflow tabs
  getSnapshot: () => { conversationId: string | null; messages: Message[] }
  restoreState: (conversationId: string | null, messages: Message[]) => void

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
  thinkingContent: '',
  pendingQuestions: [],
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
    // Also update the workflowStore's conversationId
    if (id) {
      useWorkflowStore.getState().setConversationId(id)
    }
  },

  // Ensure conversationId exists before sync operations
  ensureConversationId: () => {
    const workflowStore = useWorkflowStore.getState()
    let conversationId = workflowStore.conversationId
    if (!conversationId) {
      conversationId = crypto.randomUUID()
      workflowStore.setConversationId(conversationId)
    }
    // Sync to chatStore's local state
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
    set({ streamingContent: '', isStreaming: false, processingStatus: null, thinkingContent: '' })
  },

  // Processing status — clear thinking content when processing ends
  setProcessingStatus: (status) => set(status === null
    ? { processingStatus: null, thinkingContent: '' }
    : { processingStatus: status }),

  // Thinking stream
  appendThinkingContent: (content) =>
    set((state) => ({ thinkingContent: state.thinkingContent + content })),
  clearThinkingContent: () => set({ thinkingContent: '' }),

  // Inline question queue — enqueue appends, clear pops the front item
  enqueuePendingQuestion: (question) =>
    set((state) => ({ pendingQuestions: [...state.pendingQuestions, question] })),

  clearPendingQuestion: () =>
    set((state) => ({ pendingQuestions: state.pendingQuestions.slice(1) })),

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

  // Snapshot: returns current chat state for saving into a workflow tab
  getSnapshot: () => {
    const state = get()
    return { conversationId: state.conversationId, messages: state.messages }
  },

  // Restore: loads chat state from a workflow tab (single atomic update)
  restoreState: (conversationId, messages) =>
    set({
      conversationId,
      messages,
      isStreaming: false,
      streamingContent: '',
      currentTaskId: null,
      processingStatus: null,
      thinkingContent: '',
      pendingQuestions: [],
    }),

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
      thinkingContent: '',
      pendingQuestions: [],
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
