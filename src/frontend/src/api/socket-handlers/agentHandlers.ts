/**
 * Agent-related socket event handlers.
 * Handles: agent_error
 *
 * NOTE: agent_question and agent_complete were removed — the backend
 * never emits these events (vestigial from a prior subagent architecture).
 * Questions are now delivered via the "pending_question" event, and
 * completion is signalled via "chat_response".
 */
import type { Socket } from 'socket.io-client'
import { useChatStore, addAssistantMessage } from '../../stores/chatStore'
import { useWorkflowStore } from '../../stores/workflowStore'
import { useUIStore } from '../../stores/uiStore'
import type { SocketAgentError } from '../../types'

/** Register all agent-related socket event handlers */
export function registerAgentHandlers(socket: Socket): void {
  // Agent error
  socket.on('agent_error', (data: SocketAgentError) => {
    console.error('[Socket] agent_error:', data)
    const chatStore = useChatStore.getState()
    const uiStore = useUIStore.getState()
    const taskId = data.task_id

    if (taskId) {
      if (chatStore.isTaskCancelled(taskId)) {
        console.log('[Socket] Ignoring cancelled agent_error:', taskId)
        return
      }
      if (chatStore.currentTaskId && taskId !== chatStore.currentTaskId) {
        console.log('[Socket] Ignoring stale agent_error:', taskId)
        return
      }
    }

    chatStore.setStreaming(false)
    chatStore.clearPendingQuestion()
    chatStore.setProcessingStatus(null)
    chatStore.clearStreamContent()
    chatStore.clearCurrentTaskId()
    useWorkflowStore.getState().setPlan([])

    addAssistantMessage(`Error: ${data.error}`)
    uiStore.setError(data.error)
  })
}
