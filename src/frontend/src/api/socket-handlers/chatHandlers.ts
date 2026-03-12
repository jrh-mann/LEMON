/**
 * Chat-related Socket.IO event handlers.
 * Handles: chat_progress, chat_thinking, chat_response, chat_stream,
 *          chat_cancelled, build_user_message, context_status
 *
 * ALL events are routed to chatStore by workflow_id. Normal orchestrator events
 * include workflow_id (added by WsChatTask), and background builder events
 * include workflow_id (added by BackgroundBuilderCallbacks). This means the
 * same chatStore conversation map handles both -- no separate build buffer system.
 */
import type { Socket } from 'socket.io-client'
import { useChatStore, addAssistantMessage } from '../../stores/chatStore'
import { useUIStore } from '../../stores/uiStore'
import { useWorkflowStore } from '../../stores/workflowStore'
import type { SocketChatResponse } from '../../types'
import { resolveWorkflowId, shouldIgnoreTask } from './utils'

// Deduplication guard: prevents chat_response from being processed twice
// when Vite HMR creates duplicate socket event handler registrations.
// Without this, the second handler invocation finds streamingContent already
// cleared by the first, and addAssistantMessage creates a duplicate message.
const _processedResponses = new Set<string>()

/** Register all chat-related event handlers on the Socket.IO client */
export function registerChatHandlers(socket: Socket): void {
  // Chat progress (incremental status updates)
  socket.on('chat_progress', (data: { event: string; status?: string; tool?: string; task_id?: string; workflow_id?: string }) => {
    console.log('[SIO] chat_progress:', data)
    const workflowId = resolveWorkflowId(data)
    if (!workflowId) return

    const chatStore = useChatStore.getState()
    useUIStore.getState().clearError()
    const taskId = data.task_id

    if (shouldIgnoreTask(taskId, workflowId)) return
    // Assign task_id on first progress event so subsequent events can be filtered.
    // Accept both 'start' (normal) and 'resumed' (after page refresh reconnection).
    if (taskId && !chatStore.conversations[workflowId]?.currentTaskId && (data.event === 'start' || data.event === 'resumed')) {
      chatStore.setCurrentTaskId(workflowId, taskId)
    }

    if (data.status) {
      console.log('[SIO] Setting processing status:', data.status, 'workflow:', workflowId)
      chatStore.setProcessingStatus(workflowId, data.status)
    }
  })

  // LLM reasoning/thinking chunks streamed during analysis
  socket.on('chat_thinking', (data: { chunk: string; task_id?: string; workflow_id?: string }) => {
    const workflowId = resolveWorkflowId(data)
    if (!workflowId) return

    if (shouldIgnoreTask(data.task_id, workflowId)) return
    useChatStore.getState().appendThinkingContent(workflowId, data.chunk || '')
  })

  // Chat response (final response from LLM)
  socket.on('chat_response', (data: SocketChatResponse) => {
    console.log('[SIO] chat_response:', data)
    const workflowId = resolveWorkflowId(data)
    if (!workflowId) return

    const chatStore = useChatStore.getState()
    useUIStore.getState().clearError()
    const taskId = data.task_id

    // Always clear streaming state — every chat_response signals the task
    // is done. Early returns below prevent duplicate messages but must NOT
    // leave isStreaming stuck, which blocks the send button.
    const clearStreaming = () => {
      chatStore.setStreaming(workflowId, false)
      chatStore.setProcessingStatus(workflowId, null)
      chatStore.setCurrentTaskId(workflowId, null)
    }

    // Handle cancellation ack BEFORE shouldIgnoreTask — the task is already
    // marked cancelled by handleStop, so shouldIgnoreTask would drop this
    // event and the cleanup (clearing currentTaskId etc.) would never run.
    if (data.cancelled) {
      console.log('[SIO] chat_response: cancelled ack, cleaning up only')
      clearStreaming()
      return
    }

    // Drop events for cancelled or stale tasks. When the user clicks Stop,
    // handleStop calls markTaskCancelled + finalizeStream before the backend
    // acks. If we don't drop the ack here, the response text gets added as
    // a duplicate message. Still clear streaming so the UI isn't stuck.
    if (taskId && shouldIgnoreTask(taskId, workflowId)) {
      console.log('[SIO] chat_response DROPPED: task ignored', taskId)
      clearStreaming()
      return
    }
    if (taskId) {
      const conv = chatStore.conversations[workflowId]
      if (conv?.currentTaskId && taskId !== conv.currentTaskId) {
        console.log('[SIO] chat_response DROPPED: stale task', taskId, 'vs', conv.currentTaskId)
        clearStreaming()
        return
      }
    }

    // Deduplicate: if this task_id was already processed by a prior handler
    // invocation (from HMR-duplicated event listeners), skip it.
    if (taskId) {
      if (_processedResponses.has(taskId)) {
        console.log('[SIO] chat_response SKIPPED: already processed', taskId)
        return
      }
      _processedResponses.add(taskId)
      setTimeout(() => _processedResponses.delete(taskId), 60_000)
    }

    // Check if there's streamed content to finalize before calling finalizeStream.
    // If the orchestrator streamed, streamingContent has the text and finalizeStream
    // converts it to a Message. If it didn't stream, we use data.response instead.
    const hadStreamContent = !!(chatStore.conversations[workflowId]?.streamingContent)
    chatStore.finalizeStream(workflowId, data.tool_calls)
    chatStore.setCurrentTaskId(workflowId, null)

    // No streamed content was finalized -- add the response text directly.
    // Also add a message when tool_calls exist but response is empty, so
    // the user can see which tools ran even without accompanying text.
    if (!hadStreamContent && (data.response || data.tool_calls?.length)) {
      addAssistantMessage(data.response || '', data.tool_calls, workflowId)
    }

    // Set conversation_id if provided (normal chat responses include this)
    if (data.conversation_id) {
      chatStore.setConversationId(workflowId, data.conversation_id)
    }

    // Clear the plan checklist so it doesn't persist into the next message
    useWorkflowStore.getState().setPlan([])

    // Dispatch event so WorkflowPage can re-fetch flowchart state from DB.
    // Only fire for background builder responses -- i.e. when the event's
    // workflow_id differs from the active workflow (the user is on the parent
    // workflow while a subworkflow builds in the background), OR when the
    // conversation is marked as streaming (builder in progress).
    if (data.workflow_id) {
      const activeId = chatStore.activeWorkflowId
      const conv = chatStore.conversations[data.workflow_id]
      const isBuilderResponse = data.workflow_id !== activeId || conv?.isStreaming
      if (isBuilderResponse) {
        window.dispatchEvent(new CustomEvent('subworkflow-build-complete', {
          detail: { workflowId: data.workflow_id },
        }))
      }
    }
  })

  // Streaming response chunks
  socket.on('chat_stream', (data: { chunk: string; task_id?: string; workflow_id?: string }) => {
    const workflowId = resolveWorkflowId(data)
    if (!workflowId) return

    if (shouldIgnoreTask(data.task_id, workflowId)) return
    const chatStore = useChatStore.getState()
    // Assign task_id on first stream chunk if not yet set
    if (data.task_id && !chatStore.conversations[workflowId]?.currentTaskId) {
      chatStore.setCurrentTaskId(workflowId, data.task_id)
    }

    chatStore.setStreaming(workflowId, true)
    chatStore.appendStreamContent(workflowId, data.chunk || '')
  })

  // Chat cancelled by user
  socket.on('chat_cancelled', (data: { task_id?: string; workflow_id?: string }) => {
    console.log('[SIO] chat_cancelled:', data)
    const workflowId = resolveWorkflowId(data)
    if (!workflowId) return

    const chatStore = useChatStore.getState()

    // Only filter stale task_id — don't use shouldIgnoreTask here because
    // the task is being cancelled (markTaskCancelled must still run)
    if (data.task_id) {
      const conv = chatStore.conversations[workflowId]
      if (conv?.currentTaskId && data.task_id !== conv.currentTaskId) return
      chatStore.markTaskCancelled(data.task_id)
    }

    chatStore.setStreaming(workflowId, false)
    chatStore.setProcessingStatus(workflowId, null)
    chatStore.setCurrentTaskId(workflowId, null)
    useWorkflowStore.getState().setPlan([])
  })

  // Context window usage indicator -- emitted after each orchestrator response
  socket.on('context_status', (data: { usage_pct: number; workflow_id?: string }) => {
    const workflowId = resolveWorkflowId(data)
    if (!workflowId) return
    useChatStore.getState().setContextUsage(workflowId, data.usage_pct ?? 0)
  })

  // Initial user message from background builder -- shows the brief/prompt in chat.
  socket.on('build_user_message', (data: { workflow_id?: string; content: string }) => {
    const workflowId = resolveWorkflowId(data)
    if (!workflowId) return
    console.log('[SIO] build_user_message:', workflowId)
    const chatStore = useChatStore.getState()
    chatStore.addMessage(workflowId, {
      id: `bu_${Date.now()}`,
      role: 'user',
      content: data.content,
      timestamp: new Date().toISOString(),
      tool_calls: [],
    })
  })
}
