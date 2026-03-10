/**
 * Agent-related Socket.IO event handlers.
 * Handles: agent_error, task_finished
 *
 * NOTE: agent_question and agent_complete were removed -- the backend
 * never emits these events (vestigial from a prior subagent architecture).
 * Questions are now delivered via the "pending_question" event, and
 * completion is signalled via "chat_response".
 */
import type { Socket } from 'socket.io-client'
import { useChatStore, addAssistantMessage } from '../../stores/chatStore'
import { useWorkflowStore } from '../../stores/workflowStore'
import { useUIStore } from '../../stores/uiStore'
import { getConversationHistory } from '../workflows'
import type { SocketAgentError } from '../../types'

/** Register all agent-related event handlers on the Socket.IO client */
export function registerAgentHandlers(socket: Socket): void {

  // Task finished -- sent by resume_task when the backend task already completed
  // before the frontend could reconnect. Clears streaming state and fetches
  // the final conversation history.
  socket.on('task_finished', (data: { workflow_id?: string }) => {
    const workflowId = data.workflow_id
    if (!workflowId) return

    console.log('[SIO] task_finished -- task already done for workflow:', workflowId)
    const chatStore = useChatStore.getState()
    chatStore.setStreaming(workflowId, false)
    chatStore.setProcessingStatus(workflowId, null)
    chatStore.setCurrentTaskId(workflowId, null)

    // Fetch the final conversation from backend to get the response we missed
    const convId = chatStore.conversations?.[workflowId]?.conversationId
    if (convId) {
      getConversationHistory(convId).then((history) => {
        if (history?.messages?.length) {
          const backendMessages = history.messages
            .filter((m: { role: string }) => m.role === 'user' || m.role === 'assistant')
            .map((m: { id: string; role: string; content: string; timestamp: string; tool_calls?: unknown[] }) => ({
              id: m.id,
              role: m.role as 'user' | 'assistant',
              content: m.content,
              timestamp: m.timestamp,
              tool_calls: m.tool_calls || [],
            }))
          const localMessages = chatStore.conversations?.[workflowId]?.messages ?? []
          if (backendMessages.length > localMessages.length) {
            chatStore.setMessages(workflowId, backendMessages)
          }
        }
      }).catch(() => { /* non-critical */ })
    }
  })

  // Agent error -- route to the appropriate workflow conversation
  socket.on('agent_error', (data: SocketAgentError) => {
    console.error('[SIO] agent_error:', data)
    const chatStore = useChatStore.getState()
    const uiStore = useUIStore.getState()
    const taskId = data.task_id
    const workflowId = (data as { workflow_id?: string }).workflow_id || chatStore.activeWorkflowId

    if (taskId) {
      if (chatStore.isTaskCancelled(taskId)) {
        console.log('[SIO] Ignoring cancelled agent_error:', taskId)
        return
      }
      if (workflowId) {
        const conv = chatStore.conversations[workflowId]
        if (conv?.currentTaskId && taskId !== conv.currentTaskId) {
          console.log('[SIO] Ignoring stale agent_error:', taskId)
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
  })
}
