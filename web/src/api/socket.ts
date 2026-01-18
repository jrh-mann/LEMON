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
  if (socket?.connected) {
    return socket
  }

  const sessionId = getSessionId()
  const socketUrl = getSocketUrl()

  socket = io(socketUrl, {
    query: { session_id: sessionId },
    transports: ['websocket', 'polling'],
    reconnection: true,
    reconnectionAttempts: 5,
    reconnectionDelay: 1000,
  })

  // Connection events
  socket.on('connect', () => {
    console.log('[Socket] Connected:', socket?.id)
  })

  socket.on('disconnect', (reason) => {
    console.log('[Socket] Disconnected:', reason)
  })

  socket.on('connect_error', (error) => {
    console.error('[Socket] Connection error:', error)
    useUIStore.getState().setError('Failed to connect to server')
  })

  // Chat progress (incremental status updates)
  socket.on('chat_progress', (data: { event: string; status?: string; tool?: string }) => {
    console.log('[Socket] chat_progress:', data)
    const chatStore = useChatStore.getState()

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

    chatStore.setStreaming(false)
    chatStore.setProcessingStatus(null)

    if (data.conversation_id) {
      chatStore.setConversationId(data.conversation_id)
    }

    const streamed = chatStore.streamingContent
    const hasTools = (data.tool_calls?.length ?? 0) > 0
    if (hasTools) {
      chatStore.clearStreamContent()
      addAssistantMessage(data.response, data.tool_calls)
    } else if (streamed) {
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

    chatStore.setStreaming(false)
    chatStore.clearPendingQuestion()
    chatStore.setProcessingStatus(null)
    chatStore.clearStreamContent()

    addAssistantMessage(`Error: ${data.error}`)
    uiStore.setError(data.error)
  })

  // Streaming response chunks
  socket.on('chat_stream', (data: { chunk: string }) => {
    const chatStore = useChatStore.getState()
    if (!chatStore.isStreaming) {
      chatStore.setStreaming(true)
    }
    chatStore.appendStreamContent(data.chunk || '')
  })

  // Workflow modification events (from orchestrator editing tools)
  socket.on('workflow_modified', (data: { action: string; data: Record<string, unknown> }) => {
    console.log('[Socket] workflow_modified:', data)
    const workflowStore = useWorkflowStore.getState()
    const uiStore = useUIStore.getState()

    switch (data.action) {
      case 'create_workflow':
        // Full workflow created - load it
        if (data.data.nodes && data.data.edges) {
          // Transform backend data (top-left coords, BlockType) to frontend format
          const flowchart = transformFlowchartFromBackend(data.data as { nodes: unknown[]; edges: unknown[] })
          workflowStore.setFlowchart(flowchart)
          // Switch canvas to workflow tab to show the new workflow
          uiStore.setCanvasTab('workflow')
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

  return socket
}

export function disconnectSocket(): void {
  if (socket) {
    socket.disconnect()
    socket = null
  }
}

// Send chat message via socket
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
  chatStore.setStreaming(true)

  // Include current workflow ID so orchestrator knows what to edit
  const currentWorkflowId = workflowStore.currentWorkflow?.id

  sock.emit('chat', {
    session_id: getSessionId(),
    message,
    conversation_id: conversationId || undefined,
    image,
    current_workflow_id: currentWorkflowId,
  })
}

// Reconnect helper
export function reconnectSocket(): void {
  disconnectSocket()
  connectSocket()
}
