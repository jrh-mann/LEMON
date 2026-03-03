/**
 * Agent-related socket event handlers.
 * Handles: agent_question, agent_complete, agent_error
 */
import type { Socket } from 'socket.io-client'
import { useChatStore, addAssistantMessage } from '../../stores/chatStore'
import { useWorkflowStore } from '../../stores/workflowStore'
import { useUIStore } from '../../stores/uiStore'
import { transformFlowchartFromBackend } from '../../utils/canvas'
import type { SocketAgentQuestion, SocketAgentComplete, SocketAgentError } from '../../types'

/** Register all agent-related socket event handlers */
export function registerAgentHandlers(socket: Socket): void {
  // Agent question (needs user confirmation)
  socket.on('agent_question', (data: SocketAgentQuestion) => {
    console.log('[Socket] agent_question:', data)
    const chatStore = useChatStore.getState()

    chatStore.setStreaming(false)
    chatStore.setPendingQuestion({ question: data.question, options: [] })

    // Also add as assistant message for display
    addAssistantMessage(data.question)
  })

  // Agent complete (workflow created/updated)
  socket.on('agent_complete', (data: SocketAgentComplete) => {
    console.log('[Socket] agent_complete:', data)
    const chatStore = useChatStore.getState()
    const workflowStore = useWorkflowStore.getState()
    const uiStore = useUIStore.getState()

    chatStore.setStreaming(false)
    chatStore.clearPendingQuestion()

    addAssistantMessage(data.message)

    // If we got a workflow result, update canvas
    if (data.result?.nodes && data.result?.edges) {
      // Transform backend data (top-left coords, BlockType) to frontend format (center coords, FlowNodeType)
      const flowchart = transformFlowchartFromBackend(data.result)
      workflowStore.setFlowchart(flowchart)
    }

    uiStore.setStage('idle')
  })

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

    addAssistantMessage(`Error: ${data.error}`)
    uiStore.setError(data.error)
  })
}
