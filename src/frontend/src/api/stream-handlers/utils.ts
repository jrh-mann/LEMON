import { useChatStore } from '../../stores/chatStore'
import { useWorkflowStore } from '../../stores/workflowStore'

type WorkflowEvent = {
  workflow_id?: string | null
}

export function resolveWorkflowId(data: WorkflowEvent): string | null {
  if (data.workflow_id) {
    return data.workflow_id
  }
  return useChatStore.getState().activeWorkflowId
}

export function isForDifferentWorkflow(eventWorkflowId?: string): boolean {
  if (!eventWorkflowId) {
    return false
  }

  const currentWorkflowId = useWorkflowStore.getState().currentWorkflow?.id
  if (!currentWorkflowId) {
    return false
  }

  return currentWorkflowId !== eventWorkflowId
}

export function shouldIgnoreTask(taskId: string | undefined, workflowId: string): boolean {
  if (!taskId) {
    return false
  }

  const chatStore = useChatStore.getState()
  if (chatStore.isTaskCancelled(taskId)) {
    return true
  }

  const currentTaskId = chatStore.conversations[workflowId]?.currentTaskId
  if (!currentTaskId) {
    return false
  }

  return currentTaskId !== taskId
}
