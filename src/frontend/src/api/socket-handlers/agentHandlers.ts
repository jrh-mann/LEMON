/**
 * Agent-related WebSocket event handlers.
 * Handles: agent_error
 *
 * NOTE: agent_question and agent_complete were removed — the backend
 * never emits these events (vestigial from a prior subagent architecture).
 * Questions are now delivered via the "pending_question" event, and
 * completion is signalled via "chat_response".
 */
import { useChatStore, addAssistantMessage } from '../../stores/chatStore'
import { useWorkflowStore } from '../../stores/workflowStore'
import { useUIStore } from '../../stores/uiStore'
import type { SocketAgentError } from '../../types'
import type { HandlerMap } from './index'

/** Register all agent-related event handlers into the handler map */
export function registerAgentHandlers(handlers: HandlerMap): void {
  // Agent error — route to the appropriate workflow conversation
  handlers['agent_error'] = (data: SocketAgentError) => {
    console.error('[WS] agent_error:', data)
    const chatStore = useChatStore.getState()
    const uiStore = useUIStore.getState()
    const taskId = data.task_id
    const workflowId = (data as { workflow_id?: string }).workflow_id || chatStore.activeWorkflowId

    if (taskId) {
      if (chatStore.isTaskCancelled(taskId)) {
        console.log('[WS] Ignoring cancelled agent_error:', taskId)
        return
      }
      if (workflowId) {
        const conv = chatStore.conversations[workflowId]
        if (conv?.currentTaskId && taskId !== conv.currentTaskId) {
          console.log('[WS] Ignoring stale agent_error:', taskId)
          return
        }
      }
    }

    if (workflowId) {
      chatStore.setStreaming(workflowId, false)
      chatStore.setProcessingStatus(workflowId, null)
      chatStore.setCurrentTaskId(workflowId, null)
    }
    chatStore.clearPendingQuestion()
    useWorkflowStore.getState().setPlan([])

    addAssistantMessage(`Error: ${data.error}`, [], workflowId || undefined)
    uiStore.setError(data.error)
  }
}
