/**
 * Chat and execution action functions — all SSE/HTTP streaming.
 *
 * Chat: POST /api/chat/send → SSE stream
 * Execution: POST /api/workflows/{id}/execute → SSE stream
 * Pause/Resume/Stop: POST /api/executions/{id}/pause|resume|stop → JSON
 *
 * Exports: sendChatMessage, cancelChatTask, resumeTask,
 *          startWorkflowExecution, pauseWorkflowExecution,
 *          resumeWorkflowExecution, stopWorkflowExecution
 */
import { getSessionId, api } from './client'
import { createSSEStream, type SSEStream } from './sse'
import { useChatStore, addAssistantMessage } from '../stores/chatStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUIStore } from '../stores/uiStore'
import { transformFlowchartFromBackend, transformNodeFromBackend } from '../utils/canvas'
import { beautifyNodes } from '../utils/beautifyNodes'
import type {
  WorkflowAnalysis,
  FlowNode,
  FlowEdge,
  ExecutionLogEntry,
  PendingFile,
  ToolCall,
} from '../types'

// Module-level map of active SSE streams per workflow, for cancellation.
// Not in Zustand because SSEStream is not serializable.
const _activeStreams = new Map<string, SSEStream>()

// Separate map for execution SSE streams (one execution at a time, keyed by executionId)
const _activeExecutionStreams = new Map<string, SSEStream>()

type StreamEventHandlerMap = Record<string, (data: unknown) => void>

type ChatProgressPayload = {
  workflow_id?: string
  task_id?: string
  event?: string
  status?: string
}

type ChatChunkPayload = {
  workflow_id?: string
  task_id?: string
  chunk?: string
}

type ChatResponsePayload = {
  workflow_id?: string
  cancelled?: boolean
  tool_calls?: ToolCall[]
  response?: string
  conversation_id?: string
}

type ChatCancelledPayload = {
  workflow_id?: string
  task_id?: string
}

type WorkflowEventEdge = {
  from: string
  to: string
  label?: string
  id?: string
}

type WorkflowEventPayload = {
  workflow_id?: string
  node?: unknown
  node_id?: string
  edge?: WorkflowEventEdge
  from_node_id?: string
  to_node_id?: string
  workflow?: { nodes?: FlowNode[]; edges?: FlowEdge[] }
}

type WorkflowUpdatePayload = {
  action?: string
  data?: WorkflowEventPayload
}

type WorkflowStateAnalysisPayload = Partial<WorkflowAnalysis> & {
  output_type?: string
}

type WorkflowStateUpdatedPayload = {
  workflow_id?: string
  workflow?: { nodes?: FlowNode[]; edges?: FlowEdge[] }
  analysis?: WorkflowStateAnalysisPayload
}

type AnalysisUpdatedPayload = {
  variables?: WorkflowAnalysis['variables']
  outputs?: WorkflowAnalysis['outputs']
}

type WorkflowCreatedPayload = {
  workflow_id: string
  name?: string
  output_type?: string
}

type WorkflowSavedPayload = {
  already_saved?: boolean
  name?: string
}

type PendingQuestionPayload = {
  question: string
  options: { label: string; value: string }[]
}

type PlanUpdatedPayload = {
  items: Array<{ text: string; done: boolean }>
}

type ContextStatusPayload = {
  usage_pct?: number
}

type BuilderLifecyclePayload = {
  workflow_id?: string
  content?: string
}

type StreamErrorPayload = {
  workflow_id?: string
  error?: string
  transient?: boolean
}

type ExecutionLifecyclePayload = {
  execution_id: string
}

type ExecutionStepPayload = ExecutionLifecyclePayload & {
  node_id: string
}

type ExecutionCompletePayload = ExecutionLifecyclePayload & {
  success?: boolean
  output?: unknown
  error?: string
}

type ExecutionErrorPayload = ExecutionLifecyclePayload & {
  error?: string
}

type ExecutionLogPayload = ExecutionLifecyclePayload & {
  node_id: string
  node_label: string
  log_type: ExecutionLogEntry['log_type'] | 'subflow_start' | 'subflow_step' | 'subflow_complete' | 'start' | 'end'
  subworkflow_id?: string
  subworkflow_name?: string
  condition_expression?: string
  input_name?: string
  input_value?: unknown
  comparator?: string
  compare_value?: unknown
  compare_value2?: unknown
  result?: boolean | number
  branch_taken?: 'true' | 'false'
  output_name?: string
  operator?: string
  operands?: Array<{ name: string; kind: string; value: number }>
  formula?: string
  parent_node_id?: string
  node_type?: string
  success?: boolean
  output?: unknown
  error?: string
  inputs?: Record<string, unknown>
}

type SubflowStartPayload = ExecutionLifecyclePayload & {
  parent_node_id: string
  subworkflow_id: string
  subworkflow_name: string
  nodes: FlowNode[]
  edges: FlowEdge[]
}

type SubflowStepPayload = ExecutionLifecyclePayload & {
  subworkflow_id: string
  node_id: string
}

type OpenTabPayload = {
  workflow_id: string
  title: string
  node_count: number
  edge_count: number
  is_active: boolean
}

// ==================== Chat SSE Handlers ====================

/**
 * Build the SSE handler map for a chat turn.
 * Each handler is called when the corresponding SSE event arrives.
 * Includes handlers for builder events (subworkflow_created, etc.) that
 * now flow through the parent ChatTask's EventSink.
 */
function _buildChatSSEHandlers(workflowId: string) {
  return {
    // SSE keepalive comment — proves the connection is alive even when
    // no application events are flowing (e.g. during long tool calls).
    'keepalive': () => {
      useChatStore.getState().touchHeartbeat(workflowId)
    },

    // --- Chat streaming events ---

    'chat_progress': (rawData: unknown) => {
      const data = rawData as ChatProgressPayload
      console.log('[SSE] chat_progress:', data)
      const chatStore = useChatStore.getState()
      useUIStore.getState().clearError()

      // Route to the correct workflow — subworkflow builders tag events with their own workflow_id
      const targetWf = data.workflow_id || workflowId

      // Assign task_id on first progress event
      if (data.task_id && !chatStore.conversations[targetWf]?.currentTaskId &&
          (data.event === 'start' || data.event === 'resumed')) {
        chatStore.setCurrentTaskId(targetWf, data.task_id)
      }

      if (data.status) {
        chatStore.setProcessingStatus(targetWf, data.status)
      }
      chatStore.touchHeartbeat(targetWf)
    },

    'chat_thinking': (rawData: unknown) => {
      const data = rawData as ChatChunkPayload
      // Route to the correct workflow — subworkflow builders tag events with their own workflow_id
      const targetWf = data.workflow_id || workflowId
      // Append thinking inline into streamingContent (dimmed via .reasoning class)
      useChatStore.getState().appendThinkingInline(targetWf, data.chunk || '')
      useChatStore.getState().touchHeartbeat(targetWf)
    },

    'chat_stream': (rawData: unknown) => {
      const data = rawData as ChatChunkPayload
      const chatStore = useChatStore.getState()
      // Route to the correct workflow — subworkflow builders tag events with their own workflow_id
      const targetWf = data.workflow_id || workflowId
      // Assign task_id on first stream chunk if not yet set
      if (data.task_id && !chatStore.conversations[targetWf]?.currentTaskId) {
        chatStore.setCurrentTaskId(targetWf, data.task_id)
      }
      chatStore.setStreaming(targetWf, true)
      chatStore.appendStreamContent(targetWf, data.chunk || '')
      chatStore.touchHeartbeat(targetWf)
    },

    'chat_response': (rawData: unknown) => {
      const data = rawData as ChatResponsePayload
      console.log('[SSE] chat_response:', data)
      const chatStore = useChatStore.getState()
      useUIStore.getState().clearError()

      // Route to the correct workflow — subworkflow builders tag events with their own workflow_id
      const targetWf = data.workflow_id || workflowId

      // Always clear streaming state
      const clearStreaming = () => {
        chatStore.setStreaming(targetWf, false)
        chatStore.setProcessingStatus(targetWf, null)
        chatStore.setCurrentTaskId(targetWf, null)
      }

      if (data.cancelled) {
        console.log('[SSE] chat_response: cancelled ack, cleaning up only')
        clearStreaming()
        return
      }

      const hadStreamContent = !!(chatStore.conversations[targetWf]?.streamingContent)
      chatStore.finalizeStream(targetWf, data.tool_calls)
      chatStore.setCurrentTaskId(targetWf, null)

      if (!hadStreamContent && (data.response || data.tool_calls?.length)) {
        addAssistantMessage(data.response || '', data.tool_calls, targetWf)
      }

      if (data.conversation_id) {
        chatStore.setConversationId(targetWf, data.conversation_id)
      }

      useWorkflowStore.getState().setPlan([])

      // Dispatch event for background builder responses
      if (data.workflow_id) {
        const activeId = chatStore.activeWorkflowId
        const conv = chatStore.conversations[data.workflow_id]
        const isBuilderResponse = data.workflow_id !== activeId || conv?.isStreaming
        if (isBuilderResponse) {
          window.dispatchEvent(new CustomEvent('subworkflow-build-complete', {
            detail: { workflowId: data.workflow_id },
          }))
        }
      }
    },

    'chat_cancelled': (rawData: unknown) => {
      const data = rawData as ChatCancelledPayload
      console.log('[SSE] chat_cancelled:', data)
      const chatStore = useChatStore.getState()
      const targetWf = data.workflow_id || workflowId
      if (data.task_id) {
        chatStore.markTaskCancelled(data.task_id)
      }
      chatStore.setStreaming(targetWf, false)
      chatStore.setProcessingStatus(targetWf, null)
      chatStore.setCurrentTaskId(targetWf, null)
      useWorkflowStore.getState().setPlan([])
    },

    // --- Workflow events (emitted during tool execution) ---

    'workflow_update': (rawData: unknown) => {
      const data = rawData as WorkflowUpdatePayload
      if (!data?.data) {
        console.error('[SSE] workflow_update missing data payload:', data)
        return
      }
      console.log('[SSE] workflow_update:', data.action)
      const workflowStore = useWorkflowStore.getState()
      const uiStore = useUIStore.getState()

      // Check if event is for a different workflow (e.g. subworkflow builder)
      const eventWfId = data.data.workflow_id as string | undefined
      if (eventWfId) {
        const currentId = workflowStore.currentWorkflow?.id
        if (currentId && eventWfId !== currentId) return
      }

      try {
        switch (data.action) {
          case 'add_node':
            if (data.data.node) {
              const node = transformNodeFromBackend(data.data.node as Record<string, unknown>)
              workflowStore.addNode(node)
              uiStore.setCanvasTab('workflow')
            }
            break
          case 'modify_node':
            if (data.data.node) {
              const node = transformNodeFromBackend(data.data.node as Record<string, unknown>)
              if (workflowStore.flowchart.nodes.find(n => n.id === node.id)) {
                workflowStore.updateNode(node.id, node)
              }
            }
            break
          case 'delete_node':
            if (data.data.node_id) {
              const nodeId = data.data.node_id as string
              if (workflowStore.flowchart.nodes.find(n => n.id === nodeId)) {
                workflowStore.deleteNode(nodeId)
              }
            }
            break
          case 'add_connection':
            if (data.data.edge) {
              const edge = data.data.edge as { from: string; to: string; label?: string; id?: string }
              workflowStore.addEdge({ from: edge.from, to: edge.to, label: edge.label || '', id: edge.id })
            }
            break
          case 'delete_connection':
            if (data.data.from_node_id && data.data.to_node_id) {
              workflowStore.deleteEdge(data.data.from_node_id as string, data.data.to_node_id as string)
            }
            break
          case 'batch_edit':
            if (data.data.workflow) {
              const flowchart = transformFlowchartFromBackend(data.data.workflow)
              workflowStore.setFlowchartSilent(flowchart)
              uiStore.setCanvasTab('workflow')
            }
            break
          case 'highlight_node':
            if (data.data.node_id) {
              workflowStore.highlightNode(data.data.node_id as string)
              uiStore.setCanvasTab('workflow')
            }
            break
          default:
            console.warn('[SSE] Unknown workflow_update action:', data.action)
        }
      } catch (err) {
        console.error('[SSE] workflow_update handler error:', data.action, err)
      }
    },

    'workflow_state_updated': (rawData: unknown) => {
      const data = rawData as WorkflowStateUpdatedPayload
      console.log('[SSE] workflow_state_updated')
      const workflowStore = useWorkflowStore.getState()
      // Check if event is for a different workflow
      if (data.workflow_id) {
        const currentId = workflowStore.currentWorkflow?.id
        if (currentId && data.workflow_id !== currentId) return
      }
      if (data.workflow) {
        const flowchart = transformFlowchartFromBackend(data.workflow)
        workflowStore.setFlowchartSilent(flowchart)
      }
      if (data.analysis) {
        const currentAnalysis = workflowStore.currentAnalysis ?? { variables: [], outputs: [] }
        const updatedAnalysis: WorkflowAnalysis = {
          ...currentAnalysis,
          variables: (data.analysis.variables ?? currentAnalysis.variables) as WorkflowAnalysis['variables'],
          outputs: (data.analysis.outputs ?? currentAnalysis.outputs) as WorkflowAnalysis['outputs'],
          ...(data.analysis.output_type ? { output_type: data.analysis.output_type } : {}),
        }
        workflowStore.setAnalysis(updatedAnalysis)
      }
    },

    'analysis_updated': (rawData: unknown) => {
      const data = rawData as AnalysisUpdatedPayload
      const workflowStore = useWorkflowStore.getState()
      const currentAnalysis = workflowStore.currentAnalysis ?? { variables: [], outputs: [] }
      const updatedAnalysis: WorkflowAnalysis = {
        ...currentAnalysis,
        variables: data.variables as WorkflowAnalysis['variables'],
        outputs: data.outputs as WorkflowAnalysis['outputs'],
      }
      workflowStore.setAnalysis(updatedAnalysis)
    },

    'workflow_created': (rawData: unknown) => {
      const data = rawData as WorkflowCreatedPayload
      console.log('[SSE] workflow_created:', data)
      const store = useWorkflowStore.getState()
      const currentId = store.currentWorkflow?.id
      if (!currentId || currentId !== data.workflow_id) {
        store.setCurrentWorkflowId(data.workflow_id)
      }
      const chatStore = useChatStore.getState()
      if (!chatStore.activeWorkflowId || chatStore.activeWorkflowId !== data.workflow_id) {
        chatStore.setActiveWorkflowId(data.workflow_id)
      }
      const wf = useWorkflowStore.getState().currentWorkflow
      if (wf) {
        useWorkflowStore.getState().setCurrentWorkflow({
          ...wf,
          ...(data.name ? { metadata: { ...wf.metadata, name: data.name } } : {}),
          ...(data.output_type ? { output_type: data.output_type } : {}),
        })
      }
    },

    'workflow_saved': (rawData: unknown) => {
      const data = rawData as WorkflowSavedPayload
      console.log('[SSE] workflow_saved:', data)
      if (!data.already_saved) {
        const currentWf = useWorkflowStore.getState().currentWorkflow
        if (currentWf && data.name) {
          useWorkflowStore.getState().setCurrentWorkflow({
            ...currentWf,
            metadata: { ...currentWf.metadata, name: data.name },
          })
        }
      }
    },

    'pending_question': (rawData: unknown) => {
      const data = rawData as PendingQuestionPayload
      useChatStore.getState().enqueuePendingQuestion(data)
    },

    'plan_updated': (rawData: unknown) => {
      const data = rawData as PlanUpdatedPayload
      useWorkflowStore.getState().setPlan(data.items)
    },

    'context_status': (rawData: unknown) => {
      const data = rawData as ContextStatusPayload
      useChatStore.getState().setContextUsage(workflowId, data.usage_pct ?? 0)
    },

    // --- Builder events (flow through parent ChatTask's EventSink) ---

    'subworkflow_created': (rawData: unknown) => {
      const data = rawData as BuilderLifecyclePayload
      console.log('[SSE] subworkflow_created:', data)
      useWorkflowStore.getState().incrementLibraryRefresh()
    },

    'subworkflow_building': (rawData: unknown) => {
      const data = rawData as BuilderLifecyclePayload
      console.log('[SSE] subworkflow_building:', data)
      useWorkflowStore.getState().incrementLibraryRefresh()
    },

    'build_error': (rawData: unknown) => {
      const data = rawData as BuilderLifecyclePayload
      console.error('[SSE] build_error:', data)
      useWorkflowStore.getState().incrementLibraryRefresh()
    },

    'subworkflow_ready': (rawData: unknown) => {
      const data = rawData as BuilderLifecyclePayload
      console.log('[SSE] subworkflow_ready:', data)
      useWorkflowStore.getState().incrementLibraryRefresh()
    },

    'build_user_message': (rawData: unknown) => {
      const data = rawData as BuilderLifecyclePayload
      // Add the builder's initial prompt as a user message in the builder's conversation
      if (data.workflow_id && data.content) {
        useChatStore.getState().addMessage(data.workflow_id, {
          id: `build_${Date.now()}`,
          role: 'user',
          content: data.content,
          timestamp: new Date().toISOString(),
          tool_calls: [],
        })
      }
    },

    // --- Error events ---

    'agent_error': (rawData: unknown) => {
      const data = rawData as StreamErrorPayload
      console.error('[SSE] agent_error:', data)
      const chatStore = useChatStore.getState()
      const targetWf = data.workflow_id || workflowId
      chatStore.setStreaming(targetWf, false)
      chatStore.setProcessingStatus(targetWf, null)
      chatStore.setCurrentTaskId(targetWf, null)
      if (data.transient) {
        useUIStore.getState().setError(data.error || 'An error occurred')
      } else {
        addAssistantMessage(data.error || 'An error occurred', [], targetWf)
      }
    },

    'error': (rawData: unknown) => {
      const data = rawData as StreamErrorPayload
      console.error('[SSE] connection error:', data)
      const chatStore = useChatStore.getState()
      chatStore.setStreaming(workflowId, false)
      chatStore.setProcessingStatus(workflowId, null)
      chatStore.setCurrentTaskId(workflowId, null)
      useUIStore.getState().setError(data.error || 'Failed to send message — please try again')
    },

    'done': () => {
      // SSE stream ended — clean up the stream reference
      _activeStreams.delete(workflowId)
    },
  }
}

// ==================== Chat Actions (SSE) ====================

/**
 * Send a chat message to the backend via SSE streaming.
 *
 * The HTTP POST response IS the event stream — events are read from the
 * response body as SSE lines.
 */
export function sendChatMessage(
  message: string,
  conversationId?: string | null,
  files?: PendingFile[],
  annotations?: unknown[]
): void {
  const chatStore = useChatStore.getState()
  const workflowStore = useWorkflowStore.getState()

  // Include current workflow ID so orchestrator knows what to edit
  const currentWorkflowId = workflowStore.currentWorkflow?.id || chatStore.activeWorkflowId

  // Keep chatStore.activeWorkflowId in sync
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
  const openTabs: OpenTabPayload[] = []
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

  const payload = {
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
    analysis: workflowStore.currentAnalysis ?? undefined,
    open_tabs: openTabs,
  }

  console.log('[SSE] sendChatMessage →', {
    task_id: taskId, workflow_id: currentWorkflowId,
    message: message.slice(0, 50),
  })

  // Abort any existing stream for this workflow (prevents duplicate streams)
  const existingStream = currentWorkflowId ? _activeStreams.get(currentWorkflowId) : null
  if (existingStream) {
    existingStream.abort()
    _activeStreams.delete(currentWorkflowId!)
  }

  // Open the SSE stream — the HTTP response IS the event stream
  const handlers = _buildChatSSEHandlers(currentWorkflowId || '')
  const stream = createSSEStream('/api/chat/send', payload, handlers)

  // Store for cancellation
  if (currentWorkflowId) {
    _activeStreams.set(currentWorkflowId, stream)
  }
}

/** Cancel an in-progress chat task */
export function cancelChatTask(taskId: string): void {
  // Abort the SSE stream for immediate effect
  const chatStore = useChatStore.getState()
  const workflowId = chatStore.activeWorkflowId
  if (workflowId) {
    const stream = _activeStreams.get(workflowId)
    if (stream) {
      stream.abort()
      _activeStreams.delete(workflowId)
    }
  }

  // Also POST to the cancel endpoint (handles cases where the stream
  // abort doesn't propagate fast enough, e.g. mid-tool-call)
  api.post('/api/chat/cancel', { task_id: taskId }).catch((err) => {
    console.warn('[SSE] Cancel POST failed (stream likely already closed):', err.message)
  })
}

/**
 * Resume a running backend task after a page refresh.
 *
 * Uses SSE: POST /api/chat/resume returns an SSE stream if a task is active,
 * or JSON if the task already finished.
 */
export function resumeTask(workflowId: string): void {
  console.log('[SSE] Resuming task for workflow:', workflowId)

  // Build SSE handlers for the resumed stream
  const handlers = _buildChatSSEHandlers(workflowId)

  // POST to resume — may return SSE stream or JSON
  fetch('/api/chat/resume', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ workflow_id: workflowId }),
  }).then(async (response) => {
    const contentType = response.headers.get('content-type') || ''

    if (contentType.includes('text/event-stream')) {
      // Active task — read SSE stream
      const stream = _readResumeSSEStream(response, handlers, workflowId)
      _activeStreams.set(workflowId, stream)
    } else {
      // No active task — task already finished
      const data = await response.json()
      console.log('[SSE] Resume: no active task, fetching conversation history', data)
      // Tell the frontend to clear streaming state and refetch
      const chatStore = useChatStore.getState()
      chatStore.setStreaming(workflowId, false)
      chatStore.setProcessingStatus(workflowId, null)
      chatStore.setCurrentTaskId(workflowId, null)
      // Dispatch task_finished so WorkflowPage can re-fetch
      window.dispatchEvent(new CustomEvent('task-finished', {
        detail: { workflowId },
      }))
    }
  }).catch((err) => {
    console.error('[SSE] Resume failed:', err)
    useChatStore.getState().setStreaming(workflowId, false)
    useChatStore.getState().setProcessingStatus(workflowId, null)
    useChatStore.getState().setCurrentTaskId(workflowId, null)
  })
}

/**
 * Parse an already-fetched SSE response body. Used by resumeTask where
 * we need to inspect the content-type before deciding how to handle it.
 */
function _readResumeSSEStream(
  response: Response,
  handlers: StreamEventHandlerMap,
  workflowId: string,
): SSEStream {
  const controller = new AbortController()

  // Read the stream in the background
  ;(async () => {
    if (!response.body) return
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let currentEvent = ''
    let currentData = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        while (true) {
          const newlineIdx = buffer.indexOf('\n')
          if (newlineIdx === -1) break
          const line = buffer.slice(0, newlineIdx)
          buffer = buffer.slice(newlineIdx + 1)

          if (line === '') {
            if (currentData) {
              try {
                const parsed = JSON.parse(currentData)
                handlers[currentEvent || 'message']?.(parsed)
              } catch { /* ignore parse errors */ }
            }
            currentEvent = ''
            currentData = ''
          } else if (line.startsWith('event:')) {
            currentEvent = line.slice(6).trim()
          } else if (line.startsWith('data:')) {
            const dataLine = line.slice(5).trim()
            currentData = currentData ? `${currentData}\n${dataLine}` : dataLine
          }
        }
      }
      if (currentData) {
        try {
          const parsed = JSON.parse(currentData)
          handlers[currentEvent || 'message']?.(parsed)
        } catch { /* ignore */ }
      }
    } finally {
      reader.releaseLock()
      handlers['done']?.({})
    }
  })()

  return {
    abort: () => {
      controller.abort()
      _activeStreams.delete(workflowId)
    },
  }
}

// ==================== Execution SSE Handlers ====================

/**
 * Build the SSE handler map for a stepped workflow execution.
 * Handles stepped execution events delivered over SSE.
 */
function _buildExecutionSSEHandlers(executionId: string) {
  return {
    // Execution started — skip if already optimistically started (race condition guard)
    'execution_started': (rawData: unknown) => {
      const data = rawData as ExecutionLifecyclePayload
      console.log('[SSE] execution_started:', data)
      const workflowStore = useWorkflowStore.getState()
      if (workflowStore.execution.executionId === data.execution_id) {
        return // Already started optimistically
      }
      workflowStore.startExecution(data.execution_id)
    },

    // Execution step — highlight the current node, mark previous as executed
    'execution_step': (rawData: unknown) => {
      const data = rawData as ExecutionStepPayload
      console.log('[SSE] execution_step:', data)
      const workflowStore = useWorkflowStore.getState()
      const execution = workflowStore.execution
      if (execution.executionId !== data.execution_id) return

      if (execution.executingNodeId) {
        workflowStore.markNodeExecuted(execution.executingNodeId)
      }
      workflowStore.setExecutingNode(data.node_id)
    },

    // Execution paused
    'execution_paused': (rawData: unknown) => {
      const data = rawData as ExecutionLifecyclePayload
      console.log('[SSE] execution_paused:', data)
      const workflowStore = useWorkflowStore.getState()
      if (workflowStore.execution.executionId === data.execution_id) {
        workflowStore.pauseExecution()
      }
    },

    // Execution resumed
    'execution_resumed': (rawData: unknown) => {
      const data = rawData as ExecutionLifecyclePayload
      console.log('[SSE] execution_resumed:', data)
      const workflowStore = useWorkflowStore.getState()
      if (workflowStore.execution.executionId === data.execution_id) {
        workflowStore.resumeExecution()
      }
    },

    // Execution complete — show results in the execute modal
    'execution_complete': (rawData: unknown) => {
      const data = rawData as ExecutionCompletePayload
      console.log('[SSE] execution_complete:', data)
      const workflowStore = useWorkflowStore.getState()
      const uiStore = useUIStore.getState()
      const execution = workflowStore.execution
      if (execution.executionId !== data.execution_id) return

      if (execution.executingNodeId) {
        workflowStore.markNodeExecuted(execution.executingNodeId)
      }
      workflowStore.setExecutingNode(null)
      workflowStore.stopExecution()

      if (data.success) {
        workflowStore.setExecutionOutput(data.output)
      } else {
        workflowStore.setExecutionError(data.error || 'Execution failed')
      }
      uiStore.openModal('execute')
    },

    // Execution error — show error in the execute modal
    'execution_error': (rawData: unknown) => {
      const data = rawData as ExecutionErrorPayload
      console.error('[SSE] execution_error:', data)
      const workflowStore = useWorkflowStore.getState()
      const uiStore = useUIStore.getState()
      if (workflowStore.execution.executionId === data.execution_id) {
        workflowStore.setExecutionError(data.error || 'Execution failed')
        workflowStore.stopExecution()
        uiStore.openModal('execute')
      }
    },

    // Execution log — detailed logs for dev tools panel
    'execution_log': (rawData: unknown) => {
      const data = rawData as ExecutionLogPayload
      console.log('[SSE] execution_log:', data)
      const workflowStore = useWorkflowStore.getState()
      if (workflowStore.execution.executionId !== data.execution_id) return

      const logEntry = {
        id: `log_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
        timestamp: Date.now(),
        execution_id: data.execution_id,
        node_id: data.node_id,
        node_label: data.node_label,
        log_type: data.log_type,
        subworkflow_id: data.subworkflow_id,
        subworkflow_name: data.subworkflow_name,
        ...(data.log_type === 'decision' && {
          condition_expression: data.condition_expression,
          input_name: data.input_name,
          input_value: data.input_value,
          comparator: data.comparator,
          compare_value: data.compare_value,
          compare_value2: data.compare_value2,
          result: data.result,
          branch_taken: data.branch_taken,
        }),
        ...(data.log_type === 'calculation' && {
          output_name: data.output_name,
          operator: data.operator,
          operands: data.operands,
          result: data.result,
          formula: data.formula,
        }),
        ...(data.log_type === 'subflow_step' && {
          parent_node_id: data.parent_node_id,
          node_type: data.node_type,
        }),
        ...(data.log_type === 'subflow_complete' && {
          success: data.success,
          output: data.output,
          error: data.error,
        }),
        ...(data.log_type === 'start' && {
          inputs: data.inputs,
        }),
        ...(data.log_type === 'end' && {
          output_value: data.output,
        }),
      }
      workflowStore.addExecutionLog(logEntry as ExecutionLogEntry)
    },

    // Subflow start — opens popup modal with subflow canvas
    'subflow_start': (rawData: unknown) => {
      const data = rawData as SubflowStartPayload
      console.log('[SSE] subflow_start:', data)
      const workflowStore = useWorkflowStore.getState()
      if (workflowStore.execution.executionId !== data.execution_id) return

      const beautified = beautifyNodes(
        data.nodes as FlowNode[],
        data.edges as FlowEdge[],
      )
      workflowStore.startSubflowExecution(
        data.parent_node_id,
        data.subworkflow_id,
        data.subworkflow_name,
        beautified.nodes,
        beautified.edges,
      )
    },

    // Subflow step — highlights node in subflow popup
    'subflow_step': (rawData: unknown) => {
      const data = rawData as SubflowStepPayload
      console.log('[SSE] subflow_step:', data)
      const workflowStore = useWorkflowStore.getState()
      const { subflowStack } = workflowStore
      const topSubflow = subflowStack.length > 0 ? subflowStack[subflowStack.length - 1] : null
      if (workflowStore.execution.executionId !== data.execution_id) return
      if (!topSubflow || topSubflow.subworkflowId !== data.subworkflow_id) return

      if (topSubflow.executingNodeId) {
        workflowStore.markSubflowNodeExecuted(topSubflow.executingNodeId)
      }
      workflowStore.setSubflowExecutingNode(data.node_id)
    },

    // Subflow complete — closes popup modal
    'subflow_complete': (rawData: unknown) => {
      const data = rawData as ExecutionLifecyclePayload
      console.log('[SSE] subflow_complete:', data)
      const workflowStore = useWorkflowStore.getState()
      const { subflowStack } = workflowStore
      const topSubflow = subflowStack.length > 0 ? subflowStack[subflowStack.length - 1] : null
      if (workflowStore.execution.executionId !== data.execution_id || !topSubflow) return

      if (topSubflow.executingNodeId) {
        workflowStore.markSubflowNodeExecuted(topSubflow.executingNodeId)
      }
      const closeDelay = workflowStore.execution.executionSpeed === 0 ? 0 : 500
      setTimeout(() => {
        workflowStore.endSubflowExecution()
      }, closeDelay)
    },

    // Stream ended — clean up
    'done': () => {
      _activeExecutionStreams.delete(executionId)
    },

    'error': (rawData: unknown) => {
      const data = rawData as StreamErrorPayload
      console.error('[SSE] execution stream error:', data)
      const workflowStore = useWorkflowStore.getState()
      if (workflowStore.execution.executionId === executionId) {
        workflowStore.setExecutionError(data.error || 'Connection lost during execution')
        workflowStore.stopExecution()
        useUIStore.getState().openModal('execute')
      }
      _activeExecutionStreams.delete(executionId)
    },
  }
}

// ==================== Execution Actions (SSE + HTTP) ====================

/**
 * Start executing the current workflow with visual step-through.
 * Opens an SSE stream for execution events.
 *
 * @param inputs - Key-value pairs for workflow inputs
 * @param speedMs - Delay between steps in milliseconds (0-2000)
 * @returns The execution ID, or null on error
 */
export function startWorkflowExecution(
  inputs: Record<string, unknown>,
  speedMs?: number
): string | null {
  const workflowStore = useWorkflowStore.getState()
  const execution = workflowStore.execution

  if (execution.isExecuting) {
    console.warn('[SSE] Workflow is already executing')
    return execution.executionId
  }

  const currentWorkflow = workflowStore.currentWorkflow
  if (!currentWorkflow?.id) {
    console.error('[SSE] No current workflow to execute')
    useUIStore.getState().setError('No workflow to execute')
    return null
  }

  const executionId = `exec_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`

  const workflow = {
    nodes: workflowStore.flowchart.nodes,
    edges: workflowStore.flowchart.edges,
    variables: workflowStore.currentAnalysis?.variables ?? [],
    outputs: workflowStore.currentAnalysis?.outputs ?? [],
    output_type: currentWorkflow.output_type || 'string',
  }

  console.log('[SSE] Executing workflow:', {
    executionId,
    inputs,
    speedMs: speedMs ?? execution.executionSpeed,
    nodes: workflow.nodes.length,
    edges: workflow.edges.length,
  })

  // Optimistic update — mark execution as started immediately
  workflowStore.startExecution(executionId)

  // Build SSE handlers and open the execution stream
  const handlers = _buildExecutionSSEHandlers(executionId)
  const stream = createSSEStream(
    `/api/workflows/${currentWorkflow.id}/execute`,
    {
      execution_id: executionId,
      workflow,
      inputs,
      speed_ms: speedMs ?? execution.executionSpeed,
    },
    handlers,
  )

  _activeExecutionStreams.set(executionId, stream)

  return executionId
}

/** Pause the currently executing workflow */
export function pauseWorkflowExecution(): void {
  const workflowStore = useWorkflowStore.getState()
  const execution = workflowStore.execution

  if (!execution.isExecuting || !execution.executionId) {
    console.warn('[SSE] No active execution to pause')
    return
  }

  console.log('[SSE] Pausing execution:', execution.executionId)
  api.post(`/api/executions/${execution.executionId}/pause`).catch((err) => {
    console.error('[SSE] Pause failed:', err.message)
  })

  // Optimistic update
  workflowStore.pauseExecution()
}

/** Resume a paused workflow execution */
export function resumeWorkflowExecution(): void {
  const workflowStore = useWorkflowStore.getState()
  const execution = workflowStore.execution

  if (!execution.isPaused || !execution.executionId) {
    console.warn('[SSE] No paused execution to resume')
    return
  }

  console.log('[SSE] Resuming execution:', execution.executionId)
  api.post(`/api/executions/${execution.executionId}/resume`).catch((err) => {
    console.error('[SSE] Resume failed:', err.message)
  })

  // Optimistic update
  workflowStore.resumeExecution()
}

/** Stop the currently executing workflow */
export function stopWorkflowExecution(): void {
  const workflowStore = useWorkflowStore.getState()
  const execution = workflowStore.execution

  if (!execution.executionId) {
    console.warn('[SSE] No execution to stop')
    return
  }

  console.log('[SSE] Stopping execution:', execution.executionId)

  // Abort the SSE stream immediately
  const stream = _activeExecutionStreams.get(execution.executionId)
  if (stream) {
    stream.abort()
    _activeExecutionStreams.delete(execution.executionId)
  }

  // Also POST to the stop endpoint
  api.post(`/api/executions/${execution.executionId}/stop`).catch((err) => {
    console.error('[SSE] Stop failed:', err.message)
  })

  // Optimistic update
  workflowStore.stopExecution()
}
