/**
 * Chat-related socket event handlers.
 * Handles: chat_progress, chat_thinking, chat_response, chat_stream, chat_cancelled
 */
import type { Socket } from 'socket.io-client'
import { useChatStore, addAssistantMessage } from '../../stores/chatStore'
import { useUIStore } from '../../stores/uiStore'
import { useWorkflowStore } from '../../stores/workflowStore'
import type { SocketChatResponse } from '../../types'

/** Register all chat-related socket event handlers */
export function registerChatHandlers(socket: Socket): void {
  // Chat progress (incremental status updates)
  socket.on('chat_progress', (data: { event: string; status?: string; tool?: string; task_id?: string }) => {
    console.log('[Socket] chat_progress:', data)
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
      console.log('[Socket] Setting processing status:', data.status)
      chatStore.setProcessingStatus(data.status)
    }
  })

  // LLM reasoning/thinking chunks streamed during analysis
  socket.on('chat_thinking', (data: { chunk: string; task_id?: string }) => {
    const chatStore = useChatStore.getState()
    if (data.task_id) {
      if (chatStore.isTaskCancelled(data.task_id)) return
      if (chatStore.currentTaskId && data.task_id !== chatStore.currentTaskId) return
    }
    chatStore.appendThinkingContent(data.chunk || '')
  })

  // Chat response (final response from LLM)
  socket.on('chat_response', (data: SocketChatResponse) => {
    console.log('[Socket] chat_response:', data)
    const chatStore = useChatStore.getState()
    useUIStore.getState().clearError()
    const taskId = data.task_id

    if (taskId) {
      if (chatStore.isTaskCancelled(taskId)) {
        console.log('[Socket] Ignoring cancelled chat_response:', taskId)
        return
      }
      if (chatStore.currentTaskId && taskId !== chatStore.currentTaskId) {
        console.log('[Socket] Ignoring stale chat_response:', taskId)
        return
      }
    }
    console.log('[Socket] chat_response tool_calls:', data.tool_calls?.length || 0)
    console.log('[Socket] chat_response response_length:', data.response?.length || 0)
    console.log('[Socket] chat_response streaming_length:', chatStore.streamingContent.length)

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
  })

  // Streaming response chunks
  socket.on('chat_stream', (data: { chunk: string; task_id?: string }) => {
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
    console.log('[Socket] chat_stream chunk_length:', data.chunk?.length || 0)
    console.log('[Socket] chat_stream total_length:', chatStore.streamingContent.length)
  })

  // Chat cancelled by user
  socket.on('chat_cancelled', (data: { task_id?: string }) => {
    console.log('[Socket] chat_cancelled:', data)
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
  })
}
