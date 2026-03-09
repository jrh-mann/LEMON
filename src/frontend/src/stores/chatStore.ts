import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Message, ToolCall } from '../types'
import { useWorkflowStore } from './workflowStore'

// Shape of a single inline question from the ask_question tool
type PendingQuestion = { question: string; options: { label: string; value: string }[] }

// Per-workflow conversation state — each workflow gets its own independent conversation.
// Background builder conversations and user orchestrator conversations use the same structure.
export interface ConversationState {
  messages: Message[]
  conversationId: string | null
  isStreaming: boolean
  streamingContent: string
  thinkingContent: string
  processingStatus: string | null
  currentTaskId: string | null
  contextUsagePct: number  // 0-100, percentage of context window used
}

// Default empty conversation for new entries
const emptyConversation: ConversationState = {
  messages: [],
  conversationId: null,
  isStreaming: false,
  streamingContent: '',
  thinkingContent: '',
  processingStatus: null,
  currentTaskId: null,
  contextUsagePct: 0,
}

interface ChatState {
  // Per-workflow conversations keyed by workflow_id.
  // Both normal orchestrator chats and background builder chats live here.
  conversations: Record<string, ConversationState>

  // Which workflow's conversation is currently displayed in Chat.tsx
  activeWorkflowId: string | null

  // Global state (not per-workflow)
  cancelledTaskIds: Record<string, number>
  pendingQuestions: PendingQuestion[]

  // Workflow targeting
  setActiveWorkflowId: (id: string | null) => void

  // Per-workflow actions — all take workflowId to target the right conversation
  addMessage: (workflowId: string, message: Message) => void
  setMessages: (workflowId: string, messages: Message[]) => void
  setConversationId: (workflowId: string, id: string | null) => void
  ensureConversationId: (workflowId: string) => string
  setStreaming: (workflowId: string, streaming: boolean) => void
  appendStreamContent: (workflowId: string, content: string) => void
  setCurrentTaskId: (workflowId: string, taskId: string | null) => void
  appendThinkingContent: (workflowId: string, content: string) => void
  setProcessingStatus: (workflowId: string, status: string | null) => void
  setContextUsage: (workflowId: string, pct: number) => void
  // Finalize streaming: convert accumulated streamContent into a Message with tool_calls
  finalizeStream: (workflowId: string, toolCalls?: ToolCall[]) => void

  // Active-workflow convenience — uses activeWorkflowId
  sendUserMessage: (content: string) => Message

  // Global actions
  markTaskCancelled: (taskId: string) => void
  isTaskCancelled: (taskId: string) => boolean
  enqueuePendingQuestion: (question: PendingQuestion) => void
  clearPendingQuestion: () => void

  // Cleanup
  clearConversation: (workflowId: string) => void
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

// Helper: get conversation or return empty default (does NOT mutate state)
const getConv = (state: ChatState, workflowId: string): ConversationState =>
  state.conversations[workflowId] || emptyConversation

// Helper: produce a new conversations map with one conversation updated
const updateConv = (
  state: ChatState,
  workflowId: string,
  patch: Partial<ConversationState>,
): { conversations: Record<string, ConversationState> } => ({
  conversations: {
    ...state.conversations,
    [workflowId]: {
      ...getConv(state, workflowId),
      ...patch,
    },
  },
})

export const useChatStore = create<ChatState>()(persist((set, get) => ({
  // Initial state
  conversations: {},
  activeWorkflowId: null,
  cancelledTaskIds: {},
  pendingQuestions: [],

  // --- Workflow targeting ---

  setActiveWorkflowId: (id) => set({ activeWorkflowId: id }),

  // --- Per-workflow actions ---

  addMessage: (workflowId, message) =>
    set((state) => {
      const conv = getConv(state, workflowId)
      return updateConv(state, workflowId, {
        messages: [...conv.messages, message],
      })
    }),

  setMessages: (workflowId, messages) =>
    set((state) => updateConv(state, workflowId, { messages })),

  setConversationId: (workflowId, id) => {
    set((state) => updateConv(state, workflowId, { conversationId: id }))
    // Sync to workflowStore if this is the active workflow
    if (id && workflowId === get().activeWorkflowId) {
      useWorkflowStore.getState().setConversationId(id)
    }
  },

  ensureConversationId: (workflowId) => {
    const conv = getConv(get(), workflowId)
    if (conv.conversationId) return conv.conversationId

    // Check workflowStore for an existing conversationId
    const workflowStore = useWorkflowStore.getState()
    let conversationId = workflowStore.conversationId
    if (!conversationId) {
      conversationId = crypto.randomUUID()
      workflowStore.setConversationId(conversationId)
    }
    set((state) => updateConv(state, workflowId, { conversationId }))
    return conversationId
  },

  setStreaming: (workflowId, streaming) =>
    set((state) => updateConv(state, workflowId, { isStreaming: streaming })),

  appendStreamContent: (workflowId, content) =>
    set((state) => {
      const conv = getConv(state, workflowId)
      return updateConv(state, workflowId, {
        streamingContent: conv.streamingContent + content,
      })
    }),

  setCurrentTaskId: (workflowId, taskId) =>
    set((state) => updateConv(state, workflowId, { currentTaskId: taskId })),

  appendThinkingContent: (workflowId, content) =>
    set((state) => {
      const conv = getConv(state, workflowId)
      return updateConv(state, workflowId, {
        thinkingContent: conv.thinkingContent + content,
      })
    }),

  // Clear thinking content when processing ends (status set to null)
  setProcessingStatus: (workflowId, status) =>
    set((state) => updateConv(state, workflowId,
      status === null
        ? { processingStatus: null, thinkingContent: '' }
        : { processingStatus: status },
    )),

  setContextUsage: (workflowId, pct) =>
    set((state) => updateConv(state, workflowId, { contextUsagePct: pct })),

  // Finalize streaming: convert streamContent into a Message, clear streaming state
  finalizeStream: (workflowId, toolCalls) => {
    const conv = getConv(get(), workflowId)
    const content = conv.streamingContent
    if (content) {
      const msg: Message = {
        id: generateId(),
        role: 'assistant',
        content,
        timestamp: new Date().toISOString(),
        tool_calls: toolCalls || [],
      }
      set((state) => updateConv(state, workflowId, {
        messages: [...getConv(state, workflowId).messages, msg],
        streamingContent: '',
        isStreaming: false,
        processingStatus: null,
        thinkingContent: '',
      }))
    } else {
      set((state) => updateConv(state, workflowId, {
        isStreaming: false,
        processingStatus: null,
        thinkingContent: '',
      }))
    }
  },

  // --- Active-workflow convenience ---

  sendUserMessage: (content) => {
    // Resolve workflow ID using the SAME logic as sendChatMessage in
    // socketActions.ts: prefer workflowStore (the canonical canvas ID)
    // over chatStore.activeWorkflowId. This ensures the user message is
    // stored under the same ID that the backend will use for responses.
    const wfStoreId = useWorkflowStore.getState().currentWorkflow?.id || null
    const workflowId = wfStoreId || get().activeWorkflowId
    const message: Message = {
      id: generateId(),
      role: 'user',
      content,
      timestamp: new Date().toISOString(),
      tool_calls: [],
    }
    if (workflowId) {
      // Sync activeWorkflowId so Chat.tsx reads the right conversation
      if (get().activeWorkflowId !== workflowId) {
        get().setActiveWorkflowId(workflowId)
      }
      get().addMessage(workflowId, message)
    }
    return message
  },

  // --- Global actions ---

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
    if (!timestamp) return false
    if (now - timestamp >= CANCELLED_TASK_TTL_MS) {
      set({ cancelledTaskIds: pruneCancelledTaskIds(state.cancelledTaskIds, now) })
      return false
    }
    return true
  },

  enqueuePendingQuestion: (question) =>
    set((state) => ({ pendingQuestions: [...state.pendingQuestions, question] })),

  clearPendingQuestion: () =>
    set((state) => ({ pendingQuestions: state.pendingQuestions.slice(1) })),

  // --- Cleanup ---

  clearConversation: (workflowId) =>
    set((state) => {
      const { [workflowId]: _, ...rest } = state.conversations
      return { conversations: rest }
    }),

  reset: () =>
    set({
      conversations: {},
      activeWorkflowId: null,
      cancelledTaskIds: {},
      pendingQuestions: [],
    }),
}), {
  name: 'lemon-chat',
  // Only persist durable state — skip transient streaming/processing fields
  partialize: (state) => ({
    activeWorkflowId: state.activeWorkflowId,
    pendingQuestions: state.pendingQuestions,
    conversations: Object.fromEntries(
      Object.entries(state.conversations).map(([wfId, conv]) => [
        wfId,
        {
          messages: conv.messages,
          conversationId: conv.conversationId,
          // Reset transient fields so they don't leak across sessions
          isStreaming: false,
          streamingContent: '',
          thinkingContent: '',
          processingStatus: null,
          currentTaskId: null,
          contextUsagePct: conv.contextUsagePct,
        } satisfies ConversationState,
      ]),
    ),
  }),
}))

// Helper to add an assistant message to a specific workflow's conversation.
// Falls back to activeWorkflowId if no workflowId provided.
export const addAssistantMessage = (
  content: string,
  toolCalls: ToolCall[] = [],
  workflowId?: string,
): Message => {
  const store = useChatStore.getState()
  const wfId = workflowId || store.activeWorkflowId
  const message: Message = {
    id: generateId(),
    role: 'assistant',
    content,
    timestamp: new Date().toISOString(),
    tool_calls: toolCalls,
  }
  if (wfId) {
    store.addMessage(wfId, message)
  }
  return message
}
