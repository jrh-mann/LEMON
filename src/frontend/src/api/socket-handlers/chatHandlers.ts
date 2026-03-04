/**
 * Chat-related WebSocket event handlers.
 * Handles: chat_progress, chat_thinking, chat_response, chat_stream, chat_cancelled
 *
 * Events can come from two sources:
 * 1. Main orchestrator — tagged with task_id → routed to chatStore
 * 2. Background builder — tagged with workflow_id → routed to workflowStore
 *
 * Builder events are ALWAYS buffered into workflowStore.buildBuffers[workflow_id]
 * without filtering by currentWorkflow.id. This avoids race conditions where
 * events arrive before the async page load sets currentWorkflow.id.
 * Chat.tsx reads from the buffer keyed by the currently viewed workflow.
 */
import { useChatStore, addAssistantMessage } from '../../stores/chatStore'
import { useUIStore } from '../../stores/uiStore'
import { useWorkflowStore } from '../../stores/workflowStore'
import type { SocketChatResponse } from '../../types'
import type { HandlerMap } from './index'

/** Register all chat-related event handlers into the handler map */
export function registerChatHandlers(handlers: HandlerMap): void {
  // Chat progress (incremental status updates)
  handlers['chat_progress'] = (data: { event: string; status?: string; tool?: string; task_id?: string; workflow_id?: string }) => {
    console.log('[WS] chat_progress:', data)

    // Route builder events to workflowStore (always buffered, never filtered)
    if (data.workflow_id) {
      if (data.status) {
        useWorkflowStore.getState().setBuildProcessingStatus(data.workflow_id, data.status)
      }
      return
    }

    const chatStore = useChatStore.getState()
    useUIStore.getState().clearError()
    const taskId = data.task_id

    if (taskId) {
      if (chatStore.isTaskCancelled(taskId)) {
        return
      }
      if (chatStore.currentTaskId && taskId !== chatStore.currentTaskId) {
        return
      }
      if (!chatStore.currentTaskId && data.event === 'start') {
        chatStore.setCurrentTaskId(taskId)
      }
    }

    if (data.status) {
      console.log('[WS] Setting processing status:', data.status)
      chatStore.setProcessingStatus(data.status)
    }
  }

  // LLM reasoning/thinking chunks streamed during analysis
  handlers['chat_thinking'] = (data: { chunk: string; task_id?: string; workflow_id?: string }) => {
    // Route builder events to workflowStore (always buffered, never filtered)
    if (data.workflow_id) {
      useWorkflowStore.getState().appendBuildThinking(data.workflow_id, data.chunk || '')
      return
    }

    const chatStore = useChatStore.getState()
    if (data.task_id) {
      if (chatStore.isTaskCancelled(data.task_id)) return
      if (chatStore.currentTaskId && data.task_id !== chatStore.currentTaskId) return
    }
    chatStore.appendThinkingContent(data.chunk || '')
  }

  // Chat response (final response from LLM)
  handlers['chat_response'] = (data: SocketChatResponse) => {
    console.log('[WS] chat_response:', data)

    // Route builder events to workflowStore (always buffered, never filtered)
    if (data.workflow_id) {
      const ws = useWorkflowStore.getState()
      ws.finalizeBuildStream(data.workflow_id)
      ws.setBuildProcessingStatus(data.workflow_id, null)
      ws.setBuildToolCalls(data.workflow_id, data.tool_calls || [])
      // Dispatch event so WorkflowPage can re-fetch complete build state from DB
      window.dispatchEvent(new CustomEvent('subworkflow-build-complete', {
        detail: { workflowId: data.workflow_id },
      }))
      return
    }

    const chatStore = useChatStore.getState()
    useUIStore.getState().clearError()
    const taskId = data.task_id

    if (taskId) {
      // Accept cancelled responses when the backend explicitly sends partial results
      if (chatStore.isTaskCancelled(taskId) && !data.cancelled) {
        console.log('[WS] Ignoring cancelled chat_response:', taskId)
        return
      }
      if (chatStore.currentTaskId && taskId !== chatStore.currentTaskId) {
        console.log('[WS] Ignoring stale chat_response:', taskId)
        return
      }
    }
    console.log('[WS] chat_response tool_calls:', data.tool_calls?.length || 0)
    console.log('[WS] chat_response response_length:', data.response?.length || 0)
    console.log('[WS] chat_response streaming_length:', chatStore.streamingContent.length)
    if (data.cancelled) {
      console.log('[WS] chat_response is partial (user cancelled)')
    }

    chatStore.setStreaming(false)
    chatStore.setProcessingStatus(null)
    chatStore.clearCurrentTaskId()
    // Clear the plan checklist so it doesn't persist into the next message
    useWorkflowStore.getState().setPlan([])

    if (data.conversation_id) {
      chatStore.setConversationId(data.conversation_id)
    }

    const streamed = chatStore.streamingContent
    if (streamed) {
      addAssistantMessage(streamed, data.tool_calls)
      chatStore.clearStreamContent()
    } else {
      addAssistantMessage(data.response, data.tool_calls)
    }
  }

  // Streaming response chunks
  handlers['chat_stream'] = (data: { chunk: string; task_id?: string; workflow_id?: string }) => {
    // Route builder events to workflowStore (always buffered, never filtered)
    if (data.workflow_id) {
      const ws = useWorkflowStore.getState()
      ws.setBuildStreaming(data.workflow_id, true)
      ws.appendBuildStream(data.workflow_id, data.chunk || '')
      return
    }

    const chatStore = useChatStore.getState()
    const taskId = data.task_id

    if (taskId) {
      if (chatStore.isTaskCancelled(taskId)) {
        return
      }
      if (chatStore.currentTaskId && taskId !== chatStore.currentTaskId) {
        return
      }
      if (!chatStore.currentTaskId) {
        chatStore.setCurrentTaskId(taskId)
      }
    }

    if (!chatStore.isStreaming) {
      chatStore.setStreaming(true)
    }
    chatStore.appendStreamContent(data.chunk || '')
    console.log('[WS] chat_stream chunk_length:', data.chunk?.length || 0)
    console.log('[WS] chat_stream total_length:', chatStore.streamingContent.length)
  }

  // Chat cancelled by user
  handlers['chat_cancelled'] = (data: { task_id?: string; workflow_id?: string }) => {
    console.log('[WS] chat_cancelled:', data)

    // Route builder events to workflowStore (always buffered, never filtered)
    if (data.workflow_id) {
      const ws = useWorkflowStore.getState()
      ws.setBuildStreaming(data.workflow_id, false)
      ws.setBuildProcessingStatus(data.workflow_id, null)
      return
    }

    const chatStore = useChatStore.getState()
    const taskId = data.task_id

    if (taskId && chatStore.currentTaskId && taskId !== chatStore.currentTaskId) {
      return
    }

    if (taskId) {
      chatStore.markTaskCancelled(taskId)
    }
    chatStore.setStreaming(false)
    chatStore.setProcessingStatus(null)
    chatStore.clearCurrentTaskId()
    useWorkflowStore.getState().setPlan([])
  }
}
