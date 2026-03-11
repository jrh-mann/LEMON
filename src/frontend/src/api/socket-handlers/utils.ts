/**
 * Shared utilities for socket event handlers.
 * Centralises workflow_id resolution and task filtering to avoid
 * duplicating the same patterns across every handler module.
 */
import { useChatStore } from '../../stores/chatStore'
import { useWorkflowStore } from '../../stores/workflowStore'

/**
 * Resolve the workflow_id for an incoming socket event.
 * Falls back to chatStore.activeWorkflowId when the event doesn't include one.
 */
export function resolveWorkflowId(data: { workflow_id?: string }): string | null {
  return data.workflow_id || useChatStore.getState().activeWorkflowId
}

/**
 * Check whether an event's workflow_id matches the workflow currently
 * displayed on the canvas. Returns true if the event should be ignored
 * (i.e. it targets a different workflow).
 */
export function isForDifferentWorkflow(eventWorkflowId: string | undefined): boolean {
  if (!eventWorkflowId) return false
  const currentId = useWorkflowStore.getState().currentWorkflow?.id
  return !!currentId && eventWorkflowId !== currentId
}

/**
 * Check whether an event should be ignored because its task_id is
 * cancelled or stale relative to the active conversation.
 * Returns true if the event should be dropped.
 */
export function shouldIgnoreTask(
  taskId: string | undefined,
  workflowId: string,
): boolean {
  if (!taskId) return false
  const chatStore = useChatStore.getState()
  if (chatStore.isTaskCancelled(taskId)) return true
  const conv = chatStore.conversations[workflowId]
  if (conv?.currentTaskId && taskId !== conv.currentTaskId) return true
  return false
}
