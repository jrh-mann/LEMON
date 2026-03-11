/**
 * Socket.IO action functions -- send events to the backend.
 * Separated from connection management for clean separation of concerns.
 *
 * sendChatMessage uses HTTP POST for guaranteed delivery — the message
 * reaches the backend even if the user refreshes immediately after sending.
 * All other actions use socket events (fire-and-forget is acceptable for
 * cancellation, sync, resume, and execution control).
 *
 * Exports: sendChatMessage, cancelChatTask, syncWorkflow, resumeTask,
 *          startWorkflowExecution, pauseWorkflowExecution,
 *          resumeWorkflowExecution, stopWorkflowExecution
 */
import { getSessionId, api } from './client'
import { isConnected, sendMessage, getSocketId } from './socket'
import { useChatStore } from '../stores/chatStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUIStore } from '../stores/uiStore'

/**
 * Send a chat message to the backend via HTTP POST.
 *
 * Uses HTTP instead of socket for guaranteed delivery — if the user
 * refreshes the page immediately after sending, the message is still
 * received by the backend (the POST completes before navigation).
 * Streaming events still flow via Socket.IO (identified by socket_id).
 */
export function sendChatMessage(
  message: string,
  conversationId?: string | null,
  files?: import('../types').PendingFile[],
  annotations?: unknown[]
): void {
  const socketId = getSocketId()
  if (!socketId) {
    console.error('[SIO] Not connected — no socket ID for streaming')
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
  console.log('[HTTP] sendChatMessage files_count:', files?.length ?? 0,
    'payload_files:', filesPayload?.length ?? 0,
    'file_names:', files?.map(f => f.name) ?? [],
    'data_url_lengths:', files?.map(f => f.dataUrl?.length ?? 0) ?? [])

  // Send via HTTP POST for guaranteed delivery.
  // The backend creates the task and streams events to our socket_id.
  // Fire-and-forget from the UI's perspective — errors are caught and
  // displayed but the user doesn't need to wait for the POST to resolve.
  const payload = {
    session_id: getSessionId(),
    socket_id: socketId,
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
    analysis: workflowStore.currentAnalysis ?? undefined,
    open_tabs: openTabs,
  }

  api.post('/api/chat/send', payload).catch((err) => {
    console.error('[HTTP] sendChatMessage failed:', err)
    // Revert streaming state so the UI isn't stuck
    if (currentWorkflowId) {
      chatStore.setStreaming(currentWorkflowId, false)
      chatStore.setProcessingStatus(currentWorkflowId, null)
      chatStore.setCurrentTaskId(currentWorkflowId, null)
    }
    useUIStore.getState().setError(
      err?.message || 'Failed to send message — please try again',
    )
  })
}

/** Cancel an in-progress chat task */
export function cancelChatTask(taskId: string): void {
  if (!isConnected()) {
    console.warn('[SIO] Cannot cancel task: not connected')
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
    console.warn('[SIO] Cannot sync workflow: not connected')
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
    console.error('[SIO] Failed to generate conversation ID')
    return
  }

  const workflow = {
    nodes: workflowStore.flowchart.nodes,
    edges: workflowStore.flowchart.edges,
  }

  const analysis = workflowStore.currentAnalysis

  console.log('[SIO] Syncing workflow to backend:', {
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

/**
 * Resume a running backend task after a page refresh.
 * Tells the backend to re-route events to the new WebSocket connection.
 */
export function resumeTask(workflowId: string): void {
  if (!isConnected()) {
    console.warn('[SIO] Cannot resume task: not connected')
    return
  }
  console.log('[SIO] Resuming task for workflow:', workflowId)
  sendMessage('resume_task', { workflow_id: workflowId })
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
    console.error('[SIO] Cannot execute workflow: not connected')
    useUIStore.getState().setError('Not connected to server')
    return null
  }

  const workflowStore = useWorkflowStore.getState()
  const execution = workflowStore.execution

  // Don't start if already executing
  if (execution.isExecuting) {
    console.warn('[SIO] Workflow is already executing')
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

  console.log('[SIO] Executing workflow:', {
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
    console.warn('[SIO] Cannot pause: not connected')
    return
  }

  const workflowStore = useWorkflowStore.getState()
  const execution = workflowStore.execution

  if (!execution.isExecuting || !execution.executionId) {
    console.warn('[SIO] No active execution to pause')
    return
  }

  console.log('[SIO] Pausing execution:', execution.executionId)
  sendMessage('pause_execution', { execution_id: execution.executionId })

  // Optimistic update
  workflowStore.pauseExecution()
}

/** Resume a paused workflow execution */
export function resumeWorkflowExecution(): void {
  if (!isConnected()) {
    console.warn('[SIO] Cannot resume: not connected')
    return
  }

  const workflowStore = useWorkflowStore.getState()
  const execution = workflowStore.execution

  if (!execution.isPaused || !execution.executionId) {
    console.warn('[SIO] No paused execution to resume')
    return
  }

  console.log('[SIO] Resuming execution:', execution.executionId)
  sendMessage('resume_execution', { execution_id: execution.executionId })

  // Optimistic update
  workflowStore.resumeExecution()
}

/** Stop the currently executing workflow */
export function stopWorkflowExecution(): void {
  if (!isConnected()) {
    console.warn('[SIO] Cannot stop: not connected')
    return
  }

  const workflowStore = useWorkflowStore.getState()
  const execution = workflowStore.execution

  if (!execution.executionId) {
    console.warn('[SIO] No execution to stop')
    return
  }

  console.log('[SIO] Stopping execution:', execution.executionId)
  sendMessage('stop_execution', { execution_id: execution.executionId })

  // Optimistic update
  workflowStore.stopExecution()
}
