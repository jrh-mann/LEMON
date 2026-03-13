import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import type { Message, ToolCall } from '../types'
import { useWorkflowStore } from './workflowStore'

// Max messages persisted per conversation. Older messages are trimmed on save
// to keep localStorage usage bounded and prevent quota-exceeded errors.
const MAX_PERSISTED_MESSAGES = 100

// Resilient localStorage wrapper — catches quota errors so the app keeps
// working even when storage is full.  On quota failure it evicts the
// oldest conversations from the persisted blob and retries once.
//
// NOTE: This is a raw string-based storage adapter (StateStorage interface).
// It must be wrapped with createJSONStorage() so zustand's persist middleware
// can serialize/deserialize objects correctly.  Passing it directly as
// `storage: resilientLocalStorage` would corrupt localStorage (objects get
// stored as "[object Object]" since localStorage.setItem auto-stringifies).
const resilientLocalStorage = {
  getItem: (name: string) => localStorage.getItem(name),
  setItem: (name: string, value: string) => {
    try {
      localStorage.setItem(name, value)
    } catch (e) {
      // QuotaExceededError — evict old data and retry once
      console.warn('[chatStore] localStorage quota exceeded, evicting old conversations')
      try {
        const existing = localStorage.getItem(name)
        if (existing) {
          const parsed = JSON.parse(existing)
          const convs = parsed?.state?.conversations
          if (convs && typeof convs === 'object') {
            // Keep only the 3 most recently-touched conversations
            const entries = Object.entries(convs) as [string, any][]
            const sorted = entries.sort((a, b) => {
              const lastA = a[1]?.messages?.at(-1)?.timestamp ?? ''
              const lastB = b[1]?.messages?.at(-1)?.timestamp ?? ''
              return lastB.localeCompare(lastA)
            })
            parsed.state.conversations = Object.fromEntries(sorted.slice(0, 3))
            localStorage.setItem(name, JSON.stringify(parsed))
            return  // successfully evicted + saved
          }
        }
        // Fallback: just remove the key entirely so the app can continue
        localStorage.removeItem(name)
      } catch {
        // If even eviction fails, remove the key so the app doesn't stay broken
        try { localStorage.removeItem(name) } catch { /* give up */ }
      }
      console.warn('[chatStore] Storage eviction complete — app will continue without persisted chat')
    }
  },
  removeItem: (name: string) => localStorage.removeItem(name),
}

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
  lastHeartbeatAt: number  // Date.now() of last backend event, 0 when idle
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
  lastHeartbeatAt: 0,
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
  // Record that a backend event arrived — used by the heartbeat watchdog to detect stale tasks
  touchHeartbeat: (workflowId: string) => void
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

  setConversationId: (workflowId, id) =>
    set((state) => updateConv(state, workflowId, { conversationId: id })),

  ensureConversationId: (workflowId) => {
    const conv = getConv(get(), workflowId)
    if (conv.conversationId) return conv.conversationId

    // Generate a new ID — chatStore.conversations is the single source of truth
    const conversationId = crypto.randomUUID()
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

  touchHeartbeat: (workflowId) =>
    set((state) => updateConv(state, workflowId, { lastHeartbeatAt: Date.now() })),

  // Finalize streaming: convert streamContent into a Message, clear streaming state.
  // Only uses actual streamed response text — thinkingContent is internal reasoning
  // and must never appear as a chat message (e.g. when user cancels during thinking).
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
  // createJSONStorage wraps the raw string-based adapter with JSON
  // serialization so the persist middleware can read/write objects correctly.
  storage: createJSONStorage(() => resilientLocalStorage),
  // Only persist durable state — skip transient streaming/processing fields.
  // Trim messages to MAX_PERSISTED_MESSAGES to prevent localStorage bloat.
  partialize: (state) => ({
    activeWorkflowId: state.activeWorkflowId,
    pendingQuestions: state.pendingQuestions,
    conversations: Object.fromEntries(
      Object.entries(state.conversations).map(([wfId, conv]) => [
        wfId,
        {
          messages: conv.messages.slice(-MAX_PERSISTED_MESSAGES),
          conversationId: conv.conversationId,
          // Reset transient fields so they don't leak across sessions
          isStreaming: false,
          streamingContent: '',
          thinkingContent: '',
          processingStatus: null,
          currentTaskId: null,
          contextUsagePct: conv.contextUsagePct,
          lastHeartbeatAt: 0,
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
