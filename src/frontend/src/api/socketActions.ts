/**
 * Socket action functions — emit events to the backend.
 * Separated from handler registration for clean separation of concerns.
 *
 * Exports: sendChatMessage, cancelChatTask, syncWorkflow,
 *          startWorkflowExecution, pauseWorkflowExecution,
 *          resumeWorkflowExecution, stopWorkflowExecution
 */
import { getSessionId } from './client'
import { getSocket } from './socket'
import { useChatStore } from '../stores/chatStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUIStore } from '../stores/uiStore'

/**
 * Send a chat message to the backend via socket.
 * Includes current workflow state atomically to avoid race conditions.
 */
export function sendChatMessage(
  message: string,
  conversationId?: string | null,
  files?: import('../types').PendingFile[],
  annotations?: unknown[]
): void {
  const sock = getSocket()
  if (!sock?.connected) {
    console.error('[Socket] Not connected')
    useUIStore.getState().setError('Not connected to server')
    return
  }

  const chatStore = useChatStore.getState()
  const workflowStore = useWorkflowStore.getState()

  // Ensure conversation ID exists (generates UUID if first message)
  chatStore.ensureConversationId()

  const taskId = crypto.randomUUID()
  chatStore.setCurrentTaskId(taskId)
  chatStore.setStreaming(true)

  // Include current workflow ID so orchestrator knows what to edit
  const currentWorkflowId = workflowStore.currentWorkflow?.id

  // Get the ensured conversation ID
  const ensuredConversationId = chatStore.conversationId

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

  // Debug: log whether files are included in the payload
  const filesPayload = files && files.length > 0 ? files.map(f => ({
    id: f.id,
    name: f.name,
    data_url: f.dataUrl,
    file_type: f.type,
    purpose: f.purpose,
  })) : undefined
  console.log('[Socket] sendChatMessage files_count:', files?.length ?? 0,
    'payload_files:', filesPayload?.length ?? 0,
    'file_names:', files?.map(f => f.name) ?? [],
    'data_url_lengths:', files?.map(f => f.dataUrl?.length ?? 0) ?? [])

  // Atomic: workflow travels with message (no race conditions)
  sock.emit('chat', {
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
  const sock = getSocket()
  if (!sock?.connected) {
    console.warn('[Socket] Cannot cancel task: not connected')
    return
  }
  sock.emit('cancel_task', { task_id: taskId })
}

/**
 * Sync workflow to backend session (fire-and-forget for upload/library).
 * Chat messages now carry workflow atomically, so this is only needed for non-chat syncs.
 */
export function syncWorkflow(source: 'upload' | 'library' | 'manual' = 'manual'): void {
  const sock = getSocket()
  if (!sock?.connected) {
    console.warn('[Socket] Cannot sync workflow: not connected')
    return
  }

  const chatStore = useChatStore.getState()
  const workflowStore = useWorkflowStore.getState()

  // Ensure conversationId exists
  chatStore.ensureConversationId()
  const conversationIdVal = chatStore.conversationId

  if (!conversationIdVal) {
    console.error('[Socket] Failed to generate conversation ID')
    return
  }

  const workflow = {
    nodes: workflowStore.flowchart.nodes,
    edges: workflowStore.flowchart.edges,
  }

  const analysis = workflowStore.currentAnalysis

  console.log('[Socket] Syncing workflow to backend:', {
    source,
    conversationId: conversationIdVal,
    nodes: workflow.nodes.length,
    edges: workflow.edges.length,
    variables: analysis?.variables?.length ?? 0,
  })

  sock.emit('sync_workflow', {
    conversation_id: conversationIdVal,
    workflow,
    analysis,
    source,
  })
}

// ===== Execution Control Functions =====
// These functions emit socket events to control workflow execution on the backend

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
  const sock = getSocket()
  if (!sock?.connected) {
    console.error('[Socket] Cannot execute workflow: not connected')
    useUIStore.getState().setError('Not connected to server')
    return null
  }

  const workflowStore = useWorkflowStore.getState()
  const execution = workflowStore.execution

  // Don't start if already executing
  if (execution.isExecuting) {
    console.warn('[Socket] Workflow is already executing')
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

  console.log('[Socket] Executing workflow:', {
    executionId,
    inputs,
    speedMs: speedMs ?? execution.executionSpeed,
    nodes: workflow.nodes.length,
    edges: workflow.edges.length,
  })

  // Start execution in store (optimistic update)
  workflowStore.startExecution(executionId)

  // Emit to backend
  sock.emit('execute_workflow', {
    execution_id: executionId,
    workflow,
    inputs,
    speed_ms: speedMs ?? execution.executionSpeed,
  })

  return executionId
}

/** Pause the currently executing workflow */
export function pauseWorkflowExecution(): void {
  const sock = getSocket()
  if (!sock?.connected) {
    console.warn('[Socket] Cannot pause: not connected')
    return
  }

  const workflowStore = useWorkflowStore.getState()
  const execution = workflowStore.execution

  if (!execution.isExecuting || !execution.executionId) {
    console.warn('[Socket] No active execution to pause')
    return
  }

  console.log('[Socket] Pausing execution:', execution.executionId)
  sock.emit('pause_execution', { execution_id: execution.executionId })

  // Optimistic update
  workflowStore.pauseExecution()
}

/** Resume a paused workflow execution */
export function resumeWorkflowExecution(): void {
  const sock = getSocket()
  if (!sock?.connected) {
    console.warn('[Socket] Cannot resume: not connected')
    return
  }

  const workflowStore = useWorkflowStore.getState()
  const execution = workflowStore.execution

  if (!execution.isPaused || !execution.executionId) {
    console.warn('[Socket] No paused execution to resume')
    return
  }

  console.log('[Socket] Resuming execution:', execution.executionId)
  sock.emit('resume_execution', { execution_id: execution.executionId })

  // Optimistic update
  workflowStore.resumeExecution()
}

/** Stop the currently executing workflow */
export function stopWorkflowExecution(): void {
  const sock = getSocket()
  if (!sock?.connected) {
    console.warn('[Socket] Cannot stop: not connected')
    return
  }

  const workflowStore = useWorkflowStore.getState()
  const execution = workflowStore.execution

  if (!execution.executionId) {
    console.warn('[Socket] No execution to stop')
    return
  }

  console.log('[Socket] Stopping execution:', execution.executionId)
  sock.emit('stop_execution', { execution_id: execution.executionId })

  // Optimistic update
  workflowStore.stopExecution()
}
