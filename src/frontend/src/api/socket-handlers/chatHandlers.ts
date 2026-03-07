/**
 * Chat-related WebSocket event handlers.
 * Handles: chat_progress, chat_thinking, chat_response, chat_stream,
 *          chat_cancelled, build_user_message
 *
 * ALL events are routed to chatStore by workflow_id. Normal orchestrator events
 * include workflow_id (added by WsChatTask), and background builder events
 * include workflow_id (added by BackgroundBuilderCallbacks). This means the
 * same chatStore conversation map handles both — no separate build buffer system.
 */
import { useChatStore, addAssistantMessage } from '../../stores/chatStore'
import { useUIStore } from '../../stores/uiStore'
import { useWorkflowStore } from '../../stores/workflowStore'
import type { SocketChatResponse } from '../../types'
import type { HandlerMap } from './index'

/** Resolve the workflow_id for an event — falls back to active workflow */
function resolveWorkflowId(data: { workflow_id?: string }): string | null {
  return data.workflow_id || useChatStore.getState().activeWorkflowId
}

/** Register all chat-related event handlers into the handler map */
export function registerChatHandlers(handlers: HandlerMap): void {
  // Chat progress (incremental status updates)
  handlers['chat_progress'] = (data: { event: string; status?: string; tool?: string; task_id?: string; workflow_id?: string }) => {
    console.log('[WS] chat_progress:', data)
    const workflowId = resolveWorkflowId(data)
    if (!workflowId) return

    const chatStore = useChatStore.getState()
    useUIStore.getState().clearError()
    const taskId = data.task_id

    if (taskId) {
      if (chatStore.isTaskCancelled(taskId)) return
      const conv = chatStore.conversations[workflowId]
      if (conv?.currentTaskId && taskId !== conv.currentTaskId) return
      if (!conv?.currentTaskId && data.event === 'start') {
        chatStore.setCurrentTaskId(workflowId, taskId)
      }
    }

    if (data.status) {
      console.log('[WS] Setting processing status:', data.status, 'workflow:', workflowId)
      chatStore.setProcessingStatus(workflowId, data.status)
    }
  }

  // LLM reasoning/thinking chunks streamed during analysis
  handlers['chat_thinking'] = (data: { chunk: string; task_id?: string; workflow_id?: string }) => {
    const workflowId = resolveWorkflowId(data)
    if (!workflowId) return

    const chatStore = useChatStore.getState()
    if (data.task_id) {
      if (chatStore.isTaskCancelled(data.task_id)) return
      const conv = chatStore.conversations[workflowId]
      if (conv?.currentTaskId && data.task_id !== conv.currentTaskId) return
    }
    chatStore.appendThinkingContent(workflowId, data.chunk || '')
  }

  // Chat response (final response from LLM)
  handlers['chat_response'] = (data: SocketChatResponse) => {
    console.log('[WS] chat_response:', data)
    const workflowId = resolveWorkflowId(data)
    if (!workflowId) return

    const chatStore = useChatStore.getState()
    useUIStore.getState().clearError()
    const taskId = data.task_id

    if (taskId) {
      if (chatStore.isTaskCancelled(taskId) && !data.cancelled) {
        console.log('[WS] Ignoring cancelled chat_response:', taskId)
        return
      }
      const conv = chatStore.conversations[workflowId]
      if (conv?.currentTaskId && taskId !== conv.currentTaskId) {
        console.log('[WS] Ignoring stale chat_response:', taskId)
        return
      }
    }

    // Check if there's streamed content to finalize before calling finalizeStream.
    // If the orchestrator streamed, streamingContent has the text and finalizeStream
    // converts it to a Message. If it didn't stream, we use data.response instead.
    const hadStreamContent = !!(chatStore.conversations[workflowId]?.streamingContent)
    chatStore.finalizeStream(workflowId, data.tool_calls)
    chatStore.setCurrentTaskId(workflowId, null)

    // No streamed content was finalized — add the response text directly.
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
    // Only fire for background builder responses — i.e. when the event's
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
  }

  // Streaming response chunks
  handlers['chat_stream'] = (data: { chunk: string; task_id?: string; workflow_id?: string }) => {
    const workflowId = resolveWorkflowId(data)
    if (!workflowId) return

    const chatStore = useChatStore.getState()
    const taskId = data.task_id

    if (taskId) {
      if (chatStore.isTaskCancelled(taskId)) return
      const conv = chatStore.conversations[workflowId]
      if (conv?.currentTaskId && taskId !== conv.currentTaskId) return
      if (!conv?.currentTaskId) {
        chatStore.setCurrentTaskId(workflowId, taskId)
      }
    }

    chatStore.setStreaming(workflowId, true)
    chatStore.appendStreamContent(workflowId, data.chunk || '')
  }

  // Chat cancelled by user
  handlers['chat_cancelled'] = (data: { task_id?: string; workflow_id?: string }) => {
    console.log('[WS] chat_cancelled:', data)
    const workflowId = resolveWorkflowId(data)
    if (!workflowId) return

    const chatStore = useChatStore.getState()
    const taskId = data.task_id

    if (taskId) {
      const conv = chatStore.conversations[workflowId]
      if (conv?.currentTaskId && taskId !== conv.currentTaskId) return
      chatStore.markTaskCancelled(taskId)
    }

    chatStore.setStreaming(workflowId, false)
    chatStore.setProcessingStatus(workflowId, null)
    chatStore.setCurrentTaskId(workflowId, null)
    useWorkflowStore.getState().setPlan([])
  }

  // Context window usage indicator — emitted after each orchestrator response
  handlers['context_status'] = (data: { usage_pct: number; workflow_id?: string }) => {
    const workflowId = resolveWorkflowId(data)
    if (!workflowId) return
    useChatStore.getState().setContextUsage(workflowId, data.usage_pct ?? 0)
  }

  // Initial user message from background builder — shows the brief/prompt in chat.
  // Moved from workflowHandlers since this is a chat event.
  handlers['build_user_message'] = (data: { workflow_id: string; content: string }) => {
    console.log('[WS] build_user_message:', data.workflow_id)
    const chatStore = useChatStore.getState()
    chatStore.addMessage(data.workflow_id, {
      id: `bu_${Date.now()}`,
      role: 'user',
      content: data.content,
      timestamp: new Date().toISOString(),
      tool_calls: [],
    })
  }
}
