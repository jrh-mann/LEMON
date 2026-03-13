/**
 * Conversation recovery — syncs frontend state with backend truth.
 *
 * Used after connection loss to ensure the frontend has the complete
 * conversation history and up-to-date workflow state.
 */

import { useChatStore } from '../stores/chatStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { getConversationHistory } from '../api/workflows'
import { getWorkflow } from '../api/workflows'
import { hydrateWorkflowDetail } from './workflowHydration'

/**
 * Fetch conversation history from backend and merge into the local store.
 * Backend is source of truth — if it has more messages than the frontend,
 * the extra messages are appended. If the backend's last message is more
 * complete (e.g. the frontend only has a partial stream), it replaces the
 * frontend's version.
 */
export async function syncConversationMessages(
  workflowId: string,
  conversationId: string,
): Promise<void> {
  try {
    const history = await getConversationHistory(conversationId)
    if (!history?.messages?.length) return

    const backendMessages = history.messages
      .filter((m: { role: string; content: unknown }) =>
        (m.role === 'user' || m.role === 'assistant') &&
        typeof m.content === 'string' &&
        !(m.content as string).startsWith('[CANCELLED]')
      )
      .map((m: { role: string; content: string; id: string; timestamp: string; tool_calls?: unknown[] }) => ({
        id: m.id,
        role: m.role as 'user' | 'assistant',
        content: m.content,
        timestamp: m.timestamp,
        tool_calls: m.tool_calls || [],
      }))

    const chatStore = useChatStore.getState()
    const localMsgs = chatStore.conversations?.[workflowId]?.messages ?? []

    if (backendMessages.length > localMsgs.length) {
      // Backend has more messages — append the new ones
      const newMsgs = backendMessages.slice(localMsgs.length)
      chatStore.setMessages(workflowId, [...localMsgs, ...newMsgs])
    } else if (backendMessages.length === localMsgs.length && backendMessages.length > 0) {
      // Same count — check if the last message is more complete on the backend
      // (frontend may have a truncated partial stream)
      const lastBackend = backendMessages[backendMessages.length - 1]
      const lastLocal = localMsgs[localMsgs.length - 1]
      if (
        lastBackend.role === 'assistant' &&
        lastLocal.role === 'assistant' &&
        lastBackend.content.length > lastLocal.content.length
      ) {
        const updated = [...localMsgs]
        updated[updated.length - 1] = lastBackend
        chatStore.setMessages(workflowId, updated)
      }
    }
  } catch (err) {
    console.warn('[conversationSync] Failed to sync messages:', err)
  }
}

/**
 * Fetch the latest workflow state from backend and update the stores.
 * Ensures the canvas reflects any tool edits that happened before disconnect.
 */
export async function syncWorkflowState(workflowId: string): Promise<void> {
  try {
    const workflowData = await getWorkflow(workflowId)
    const { workflow, flowchart, analysis } = hydrateWorkflowDetail(workflowData)
    const store = useWorkflowStore.getState()
    store.setCurrentWorkflow(workflow)
    store.setFlowchart(flowchart)
    store.setAnalysis(analysis)
  } catch (err) {
    console.warn('[conversationSync] Failed to sync workflow state:', err)
  }
}
