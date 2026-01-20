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
    const hasTools = (data.tool_calls?.length ?? 0) > 0
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

    const updatedAnalysis: WorkflowAnalysis = {
      ...currentAnalysis,
      inputs: data.inputs as WorkflowAnalysis['inputs'],
      outputs: data.outputs as WorkflowAnalysis['outputs'],
    }

    workflowStore.setAnalysis(updatedAnalysis)
    console.log('[Socket] Updated analysis with', data.inputs.length, 'inputs and', data.outputs.length, 'outputs')
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
