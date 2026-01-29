import { io, Socket } from 'socket.io-client'
import { getSessionId } from './client'
import { useChatStore, addAssistantMessage } from '../stores/chatStore'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUIStore } from '../stores/uiStore'
import { transformFlowchartFromBackend, transformNodeFromBackend } from '../utils/canvas'
import type {
  SocketChatResponse,
  SocketAgentQuestion,
  SocketAgentComplete,
  SocketAgentError,
  WorkflowAnalysis,
} from '../types'

let socket: Socket | null = null

// Get socket server URL - uses Vite proxy in dev, env var in production
function getSocketUrl(): string {
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL
  }
  // In development with Vite proxy, connect to same origin
  return window.location.origin
}

export function getSocket(): Socket | null {
  return socket
}

export function connectSocket(): Socket {
  if (socket) {
    return socket
  }

  const sessionId = getSessionId()
  const socketUrl = getSocketUrl()

  socket = io(socketUrl, {
    query: { session_id: sessionId },
    transports: ['polling'],
    upgrade: false,
    withCredentials: true,
    reconnection: true,
    reconnectionAttempts: 5,
    reconnectionDelay: 1000,
  })

  // Connection events
  socket.on('connect', () => {
    console.log('[Socket] Connected:', socket?.id)
    useUIStore.getState().clearError()
  })

  socket.on('disconnect', (reason) => {
    console.log('[Socket] Disconnected:', reason)
  })

  socket.on('connect_error', (error) => {
    console.error('[Socket] Connection error:', error)
    if (!socket?.connected) {
      const message = (error as Error)?.message || String(error)
      useUIStore.getState().setError(`Failed to connect to server: ${message}`)
    }
  })

  // Chat progress (incremental status updates)
  socket.on('chat_progress', (data: { event: string; status?: string; tool?: string; task_id?: string }) => {
    console.log('[Socket] chat_progress:', data)
    const chatStore = useChatStore.getState()
    useUIStore.getState().clearError()
    const taskId = data.task_id

    if (taskId) {
      if (chatStore.isTaskCancelled(taskId)) {
        return
      }
      if (chatStore.currentTaskId && taskId !== chatStore.currentTaskId) {
        return
      }
      if (!chatStore.currentTaskId && data.event === 'start') {
        chatStore.setCurrentTaskId(taskId)
      }
    }

    if (data.tool === 'analyze_workflow' && !data.status) {
      chatStore.setProcessingStatus('Analyzing workflow...')
      return
    }

    if (data.status) {
      console.log('[Socket] Setting processing status:', data.status)
      chatStore.setProcessingStatus(data.status)
    }
  })

  // Debug: log all incoming events
  socket.onAny((event, ...args) => {
    console.log('[Socket] Event:', event, args)
  })

  // Chat response
  socket.on('chat_response', (data: SocketChatResponse) => {
    console.log('[Socket] chat_response:', data)
    const chatStore = useChatStore.getState()
    useUIStore.getState().clearError()
    const taskId = data.task_id

    if (taskId) {
      if (chatStore.isTaskCancelled(taskId)) {
        console.log('[Socket] Ignoring cancelled chat_response:', taskId)
        return
      }
      if (chatStore.currentTaskId && taskId !== chatStore.currentTaskId) {
        console.log('[Socket] Ignoring stale chat_response:', taskId)
        return
      }
    }
    console.log('[Socket] chat_response tool_calls:', data.tool_calls?.length || 0)
    console.log('[Socket] chat_response response_length:', data.response?.length || 0)
    console.log('[Socket] chat_response streaming_length:', chatStore.streamingContent.length)

    chatStore.setStreaming(false)
    chatStore.setProcessingStatus(null)
    chatStore.clearCurrentTaskId()

    if (data.conversation_id) {
      chatStore.setConversationId(data.conversation_id)
    }

    const streamed = chatStore.streamingContent
    if (streamed) {
      addAssistantMessage(streamed, data.tool_calls)
      chatStore.clearStreamContent()
    } else {
      addAssistantMessage(data.response, data.tool_calls)
    }
  })

  // Agent question (needs user confirmation)
  socket.on('agent_question', (data: SocketAgentQuestion) => {
    console.log('[Socket] agent_question:', data)
    const chatStore = useChatStore.getState()

    chatStore.setStreaming(false)
    chatStore.setPendingQuestion(data.question, data.task_id)

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

  // Streaming response chunks
  socket.on('chat_stream', (data: { chunk: string; task_id?: string }) => {
    const chatStore = useChatStore.getState()
    const taskId = data.task_id

    if (taskId) {
      if (chatStore.isTaskCancelled(taskId)) {
        return
      }
      if (chatStore.currentTaskId && taskId !== chatStore.currentTaskId) {
        return
      }
      if (!chatStore.currentTaskId) {
        chatStore.setCurrentTaskId(taskId)
      }
    }

    if (!chatStore.isStreaming) {
      chatStore.setStreaming(true)
    }
    chatStore.appendStreamContent(data.chunk || '')
    console.log('[Socket] chat_stream chunk_length:', data.chunk?.length || 0)
    console.log('[Socket] chat_stream total_length:', chatStore.streamingContent.length)
  })

  socket.on('chat_cancelled', (data: { task_id?: string }) => {
    console.log('[Socket] chat_cancelled:', data)
    const chatStore = useChatStore.getState()
    const taskId = data.task_id

    if (taskId && chatStore.currentTaskId && taskId !== chatStore.currentTaskId) {
      return
    }

    if (taskId) {
      chatStore.markTaskCancelled(taskId)
    }
    chatStore.setStreaming(false)
    chatStore.setProcessingStatus(null)
    chatStore.clearCurrentTaskId()
  })

  // Workflow modification events (from orchestrator editing tools)
  socket.on('workflow_modified', (data: { action: string; data: Record<string, unknown> }) => {
    console.log('[Socket] workflow_modified:', data)
    const workflowStore = useWorkflowStore.getState()
    const uiStore = useUIStore.getState()

    switch (data.action) {
      case 'create_workflow':
        // Full workflow created - load it
        {
          const payload = data.data as {
            flowchart?: { nodes?: unknown[]; edges?: unknown[] }
            analysis?: WorkflowAnalysis
            nodes?: unknown[]
            edges?: unknown[]
          }
          if (payload.analysis) {
            workflowStore.setAnalysis(payload.analysis)
          }
          const flowchartData = payload.flowchart?.nodes ? payload.flowchart : payload
          if (flowchartData.nodes && flowchartData.edges) {
            // Transform backend data (top-left coords, BlockType) to frontend format
            const flowchart = transformFlowchartFromBackend(flowchartData as { nodes: unknown[]; edges: unknown[] })
            workflowStore.setFlowchart(flowchart)
            // Switch canvas to workflow tab to show the new workflow
            uiStore.setCanvasTab('workflow')
            // Sync workflow to backend session (establish backend as source of truth)
            syncWorkflow('upload')
          }
        }
        break

      case 'add_block':
        // Single block added - transform from backend format
        if (data.data.node) {
          const node = transformNodeFromBackend(data.data.node as Record<string, unknown>)
          workflowStore.addNode(node)
        }
        break

      case 'update_block':
        // Block updated - transform from backend format
        if (data.data.node) {
          const node = transformNodeFromBackend(data.data.node as Record<string, unknown>)
          workflowStore.updateNode(node.id, node)
        }
        break

      case 'delete_block':
        // Block deleted
        if (data.data.deleted_block_id) {
          workflowStore.deleteNode(data.data.deleted_block_id as string)
        }
        break

      case 'connect_blocks':
        // Edge added
        if (data.data.edge) {
          const edge = data.data.edge as typeof workflowStore.flowchart.edges[0]
          workflowStore.addEdge(edge)
        }
        break

      case 'disconnect_blocks':
        // Edge removed
        if (data.data.removed_connection_id) {
          workflowStore.deleteEdgeById(data.data.removed_connection_id as string)
        }
        break

      default:
        console.warn('[Socket] Unknown workflow action:', data.action)
    }
  })

  // Workflow update events (from orchestrator manipulation tools)
  socket.on('workflow_update', (data: { action: string; data: Record<string, unknown> }) => {
    console.log('[Socket] workflow_update:', data)
    const workflowStore = useWorkflowStore.getState()
    const uiStore = useUIStore.getState()

    switch (data.action) {
      case 'add_node':
        // Single node added by orchestrator
        if (data.data.node) {
          const node = transformNodeFromBackend(data.data.node as Record<string, unknown>)
          workflowStore.addNode(node)
          // Switch to workflow tab to show the change
          uiStore.setCanvasTab('workflow')
          console.log('[Socket] Added node:', node.id)
        }
        break

      case 'modify_node':
        // Node updated by orchestrator
        if (data.data.node) {
          const node = transformNodeFromBackend(data.data.node as Record<string, unknown>)
          const exists = workflowStore.flowchart.nodes.find(n => n.id === node.id)
          if (!exists) {
            console.error('[Socket] Cannot modify non-existent node:', node.id)
            break
          }
          workflowStore.updateNode(node.id, node)
          console.log('[Socket] Modified node:', node.id)
        }
        break

      case 'delete_node':
        // Node deleted by orchestrator
        if (data.data.node_id) {
          const nodeId = data.data.node_id as string
          const exists = workflowStore.flowchart.nodes.find(n => n.id === nodeId)
          if (!exists) {
            console.error('[Socket] Cannot delete non-existent node:', nodeId)
            break
          }
          workflowStore.deleteNode(nodeId)
          console.log('[Socket] Deleted node:', nodeId)
          // Note: deleteNode() automatically removes connected edges
        }
        break

      case 'add_connection':
        // Edge added by orchestrator
        if (data.data.edge) {
          const edge = data.data.edge as {
            from: string
            to: string
            label?: string
            id?: string
          }
          workflowStore.addEdge({
            from: edge.from,
            to: edge.to,
            label: edge.label || '',
            id: edge.id,
          })
          console.log('[Socket] Added connection:', edge.from, '->', edge.to)
        }
        break

      case 'delete_connection':
        // Edge removed by orchestrator
        if (data.data.from_node_id && data.data.to_node_id) {
          const fromId = data.data.from_node_id as string
          const toId = data.data.to_node_id as string
          workflowStore.deleteEdge(fromId, toId)
          console.log('[Socket] Deleted connection:', fromId, '->', toId)
        }
        break

      case 'batch_edit':
        // Multiple operations applied atomically
        if (data.data.workflow) {
          const flowchart = transformFlowchartFromBackend(
            data.data.workflow as { nodes: unknown[]; edges: unknown[] }
          )
          workflowStore.setFlowchart(flowchart)
          // Switch to workflow tab to show the changes
          uiStore.setCanvasTab('workflow')
          console.log('[Socket] Applied batch edit:', data.data.operations_applied, 'operations')
        }
        break

      default:
        console.warn('[Socket] Unknown workflow_update action:', data.action)
    }
  })

  // Analysis updates (from input management tools)
  socket.on('analysis_updated', (data: { inputs: unknown[]; outputs: unknown[] }) => {
    console.log('[Socket] analysis_updated:', data)
    const workflowStore = useWorkflowStore.getState()

    // Update the analysis with new inputs/outputs
    const currentAnalysis = workflowStore.currentAnalysis ?? {
      inputs: [],
      outputs: [],
      tree: {},
      doubts: [],
    }

    // Map backend 'inputs' field to frontend 'variables' field for unified variable system
    const updatedAnalysis: WorkflowAnalysis = {
      ...currentAnalysis,
      variables: data.inputs as WorkflowAnalysis['variables'],
      outputs: data.outputs as WorkflowAnalysis['outputs'],
    }

    workflowStore.setAnalysis(updatedAnalysis)
    console.log('[Socket] Updated analysis with', data.inputs.length, 'variables and', data.outputs.length, 'outputs')
  })

  // ===== Execution Events =====
  // These events handle visual workflow execution (highlighting nodes as they execute)

  // Execution started - marks the beginning of a workflow execution session
  socket.on('execution_started', (data: { execution_id: string }) => {
    console.log('[Socket] execution_started:', data)
    const workflowStore = useWorkflowStore.getState()
    workflowStore.startExecution(data.execution_id)
  })

  // Execution step - fires when a node begins executing (highlight it)
  socket.on('execution_step', (data: {
    execution_id: string
    node_id: string
    node_type: string
    node_label: string
    step_index: number
  }) => {
    console.log('[Socket] execution_step:', data)
    const workflowStore = useWorkflowStore.getState()
    const execution = workflowStore.execution

    // Only process if this is our current execution
    if (execution.executionId !== data.execution_id) {
      console.warn('[Socket] Ignoring step from different execution')
      return
    }

    // Mark the previous executing node as executed (trail effect)
    if (execution.executingNodeId) {
      workflowStore.markNodeExecuted(execution.executingNodeId)
    }

    // Set the new executing node
    workflowStore.setExecutingNode(data.node_id)
  })

  // Execution paused - user requested pause
  socket.on('execution_paused', (data: { execution_id: string; current_node_id: string }) => {
    console.log('[Socket] execution_paused:', data)
    const workflowStore = useWorkflowStore.getState()

    if (workflowStore.execution.executionId === data.execution_id) {
      workflowStore.pauseExecution()
    }
  })

  // Execution resumed - user requested resume
  socket.on('execution_resumed', (data: { execution_id: string }) => {
    console.log('[Socket] execution_resumed:', data)
    const workflowStore = useWorkflowStore.getState()

    if (workflowStore.execution.executionId === data.execution_id) {
      workflowStore.resumeExecution()
    }
  })

  // Execution complete - workflow finished executing (success or failure)
  // Reopens the execute modal to show results to user
  socket.on('execution_complete', (data: {
    execution_id: string
    success: boolean
    output?: unknown
    path?: string[]
    error?: string
  }) => {
    console.log('[Socket] execution_complete:', data)
    const workflowStore = useWorkflowStore.getState()
    const uiStore = useUIStore.getState()
    const execution = workflowStore.execution

    if (execution.executionId !== data.execution_id) {
      console.warn('[Socket] Ignoring completion from different execution')
      return
    }

    // Mark the last executing node as executed
    if (execution.executingNodeId) {
      workflowStore.markNodeExecuted(execution.executingNodeId)
    }

    // Clear executing node and set output
    workflowStore.setExecutingNode(null)
    workflowStore.stopExecution()

    if (data.success) {
      workflowStore.setExecutionOutput(data.output)
    } else {
      workflowStore.setExecutionError(data.error || 'Execution failed')
    }

    // Reopen the execute modal to show results/error to user
    uiStore.openModal('execute')
  })

  // Execution error - something went wrong during execution
  // Reopens the execute modal to show error to user
  socket.on('execution_error', (data: { execution_id: string; error: string }) => {
    console.error('[Socket] execution_error:', data)
    const workflowStore = useWorkflowStore.getState()
    const uiStore = useUIStore.getState()

    if (workflowStore.execution.executionId === data.execution_id) {
      workflowStore.setExecutionError(data.error)
      workflowStore.stopExecution()
      // Reopen the execute modal to show error to user
      uiStore.openModal('execute')
    }
  })

  return socket
}

export function disconnectSocket(): void {
  if (socket) {
    socket.disconnect()
    socket = null
  }
}

// Send chat message via socket (includes workflow atomically in payload)
export function sendChatMessage(
  message: string,
  conversationId?: string | null,
  image?: string
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

  // Atomic: workflow travels with message (no race conditions)
  sock.emit('chat', {
    session_id: getSessionId(),
    message,
    conversation_id: ensuredConversationId || conversationId || undefined,
    image,
    task_id: taskId,
    current_workflow_id: currentWorkflowId,
    workflow: {
      nodes: workflowStore.flowchart.nodes,
      edges: workflowStore.flowchart.edges,
    },
  })
}

export function cancelChatTask(taskId: string): void {
  const sock = getSocket()
  if (!sock?.connected) {
    console.warn('[Socket] Cannot cancel task: not connected')
    return
  }
  sock.emit('cancel_task', { task_id: taskId })
}

// Sync workflow to backend session (fire-and-forget for upload/library)
// Chat messages now carry workflow atomically, so this is only needed for non-chat syncs
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
  const conversationId = chatStore.conversationId

  if (!conversationId) {
    console.error('[Socket] Failed to generate conversation ID')
    return
  }

  const workflow = {
    nodes: workflowStore.flowchart.nodes,
    edges: workflowStore.flowchart.edges,
  }

  console.log('[Socket] Syncing workflow to backend:', {
    source,
    conversationId,
    nodes: workflow.nodes.length,
    edges: workflow.edges.length,
  })

  sock.emit('sync_workflow', {
    conversation_id: conversationId,
    workflow,
    source,
  })
}

// Reconnect helper
export function reconnectSocket(): void {
  disconnectSocket()
  connectSocket()
}

// ===== Execution Control Functions =====
// These functions emit socket events to control workflow execution on the backend

/**
 * Start executing the current workflow with visual step-through
 * @param inputs - Key-value pairs for workflow inputs
 * @param speedMs - Delay between steps in milliseconds (100-2000)
 * @returns The execution ID
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
    inputs: workflowStore.currentAnalysis?.variables ?? [],  // Backend expects 'inputs'
    outputs: workflowStore.currentAnalysis?.outputs ?? [],
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

/**
 * Pause the currently executing workflow
 */
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

/**
 * Resume a paused workflow execution
 */
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

/**
 * Stop the currently executing workflow
 */
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
