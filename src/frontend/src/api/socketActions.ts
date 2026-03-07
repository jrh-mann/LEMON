/**
 * WebSocket action functions — send messages to the backend.
 * Separated from connection management for clean separation of concerns.
 *
 * Exports: sendChatMessage, cancelChatTask, syncWorkflow,
 *          startWorkflowExecution, pauseWorkflowExecution,
 *          resumeWorkflowExecution, stopWorkflowExecution
 */
import { getSessionId } from './client'
import { isConnected, sendMessage } from './socket'
import { useChatStore } from '../stores/chatStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUIStore } from '../stores/uiStore'

/**
 * Send a chat message to the backend via WebSocket.
 * Includes current workflow state atomically to avoid race conditions.
 */
export function sendChatMessage(
  message: string,
  conversationId?: string | null,
  files?: import('../types').PendingFile[],
  annotations?: unknown[]
): void {
  if (!isConnected()) {
    console.error('[WS] Not connected')
    useUIStore.getState().setError('Not connected to server')
    return
  }

  const chatStore = useChatStore.getState()
  const workflowStore = useWorkflowStore.getState()

  // Include current workflow ID so orchestrator knows what to edit
  const currentWorkflowId = workflowStore.currentWorkflow?.id || chatStore.activeWorkflowId

  // Keep chatStore.activeWorkflowId in sync — the Chat component reads from it
  if (currentWorkflowId && chatStore.activeWorkflowId !== currentWorkflowId) {
    chatStore.setActiveWorkflowId(currentWorkflowId)
  }

  // Ensure conversation ID exists (generates UUID if first message)
  const ensuredConversationId = currentWorkflowId
    ? chatStore.ensureConversationId(currentWorkflowId)
    : conversationId || undefined

  const taskId = crypto.randomUUID()
  if (currentWorkflowId) {
    chatStore.setCurrentTaskId(currentWorkflowId, taskId)
    chatStore.setStreaming(currentWorkflowId, true)
  }

  // Collect info about the active unsaved workflow
  const openTabs: any[] = []
  const currentWf = workflowStore.currentWorkflow
  if (currentWf && workflowStore.flowchart.nodes.length > 0) {
    openTabs.push({
      workflow_id: currentWf.id,
      title: currentWf.metadata?.name || 'New Workflow',
      node_count: workflowStore.flowchart.nodes.length,
      edge_count: workflowStore.flowchart.edges.length,
      is_active: true,
    })
  }

  // Build file payload
  const filesPayload = files && files.length > 0 ? files.map(f => ({
    id: f.id,
    name: f.name,
    data_url: f.dataUrl,
    file_type: f.type,
    purpose: f.purpose,
  })) : undefined
  console.log('[WS] sendChatMessage files_count:', files?.length ?? 0,
    'payload_files:', filesPayload?.length ?? 0,
    'file_names:', files?.map(f => f.name) ?? [],
    'data_url_lengths:', files?.map(f => f.dataUrl?.length ?? 0) ?? [])

  // Atomic: workflow travels with message (no race conditions)
  sendMessage('chat', {
    session_id: getSessionId(),
    message,
    conversation_id: ensuredConversationId || conversationId || undefined,
    files: filesPayload,
    annotations: annotations && annotations.length > 0 ? annotations : undefined,
    task_id: taskId,
    current_workflow_id: currentWorkflowId,
    workflow: {
      nodes: workflowStore.flowchart.nodes,
      edges: workflowStore.flowchart.edges,
    },
    // Include analysis so backend has current variables
    analysis: workflowStore.currentAnalysis ?? undefined,
    // Include all open tabs so list_workflows_in_library can show all drafts
    open_tabs: openTabs,
  })
}

/** Cancel an in-progress chat task */
export function cancelChatTask(taskId: string): void {
  if (!isConnected()) {
    console.warn('[WS] Cannot cancel task: not connected')
    return
  }
  sendMessage('cancel_task', { task_id: taskId })
}

/**
 * Sync workflow to backend session (fire-and-forget for upload/library).
 * Chat messages now carry workflow atomically, so this is only needed for non-chat syncs.
 */
export function syncWorkflow(source: 'upload' | 'library' | 'manual' = 'manual'): void {
  if (!isConnected()) {
    console.warn('[WS] Cannot sync workflow: not connected')
    return
  }

  const chatStore = useChatStore.getState()
  const workflowStore = useWorkflowStore.getState()

  // Ensure conversationId exists for the active workflow
  const activeWfId = workflowStore.currentWorkflow?.id || chatStore.activeWorkflowId
  const conversationIdVal = activeWfId
    ? chatStore.ensureConversationId(activeWfId)
    : null

  if (!conversationIdVal) {
    console.error('[WS] Failed to generate conversation ID')
    return
  }

  const workflow = {
    nodes: workflowStore.flowchart.nodes,
    edges: workflowStore.flowchart.edges,
  }

  const analysis = workflowStore.currentAnalysis

  console.log('[WS] Syncing workflow to backend:', {
    source,
    conversationId: conversationIdVal,
    nodes: workflow.nodes.length,
    edges: workflow.edges.length,
    variables: analysis?.variables?.length ?? 0,
  })

  sendMessage('sync_workflow', {
    conversation_id: conversationIdVal,
    workflow,
    analysis,
    source,
  })
}

// ===== Execution Control Functions =====
// These functions send WebSocket messages to control workflow execution on the backend

/**
 * Start executing the current workflow with visual step-through.
 * @param inputs - Key-value pairs for workflow inputs
 * @param speedMs - Delay between steps in milliseconds (100-2000)
 * @returns The execution ID, or null if not connected
 */
export function startWorkflowExecution(
  inputs: Record<string, unknown>,
  speedMs?: number
): string | null {
  if (!isConnected()) {
    console.error('[WS] Cannot execute workflow: not connected')
    useUIStore.getState().setError('Not connected to server')
    return null
  }

  const workflowStore = useWorkflowStore.getState()
  const execution = workflowStore.execution

  // Don't start if already executing
  if (execution.isExecuting) {
    console.warn('[WS] Workflow is already executing')
    return execution.executionId
  }

  // Generate execution ID
  const executionId = `exec_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`

  // Get workflow data including variables from analysis
  const workflow = {
    nodes: workflowStore.flowchart.nodes,
    edges: workflowStore.flowchart.edges,
    variables: workflowStore.currentAnalysis?.variables ?? [],
    outputs: workflowStore.currentAnalysis?.outputs ?? [],
    output_type: workflowStore.currentWorkflow?.output_type || 'string',
  }

  console.log('[WS] Executing workflow:', {
    executionId,
    inputs,
    speedMs: speedMs ?? execution.executionSpeed,
    nodes: workflow.nodes.length,
    edges: workflow.edges.length,
  })

  // Start execution in store (optimistic update)
  workflowStore.startExecution(executionId)

  // Send to backend
  sendMessage('execute_workflow', {
    execution_id: executionId,
    workflow,
    inputs,
    speed_ms: speedMs ?? execution.executionSpeed,
  })

  return executionId
}

/** Pause the currently executing workflow */
export function pauseWorkflowExecution(): void {
  if (!isConnected()) {
    console.warn('[WS] Cannot pause: not connected')
    return
  }

  const workflowStore = useWorkflowStore.getState()
  const execution = workflowStore.execution

  if (!execution.isExecuting || !execution.executionId) {
    console.warn('[WS] No active execution to pause')
    return
  }

  console.log('[WS] Pausing execution:', execution.executionId)
  sendMessage('pause_execution', { execution_id: execution.executionId })

  // Optimistic update
  workflowStore.pauseExecution()
}

/** Resume a paused workflow execution */
export function resumeWorkflowExecution(): void {
  if (!isConnected()) {
    console.warn('[WS] Cannot resume: not connected')
    return
  }

  const workflowStore = useWorkflowStore.getState()
  const execution = workflowStore.execution

  if (!execution.isPaused || !execution.executionId) {
    console.warn('[WS] No paused execution to resume')
    return
  }

  console.log('[WS] Resuming execution:', execution.executionId)
  sendMessage('resume_execution', { execution_id: execution.executionId })

  // Optimistic update
  workflowStore.resumeExecution()
}

/** Stop the currently executing workflow */
export function stopWorkflowExecution(): void {
  if (!isConnected()) {
    console.warn('[WS] Cannot stop: not connected')
    return
  }

  const workflowStore = useWorkflowStore.getState()
  const execution = workflowStore.execution

  if (!execution.executionId) {
    console.warn('[WS] No execution to stop')
    return
  }

  console.log('[WS] Stopping execution:', execution.executionId)
  sendMessage('stop_execution', { execution_id: execution.executionId })

  // Optimistic update
  workflowStore.stopExecution()
}
