/**
 * Socket connection management — singleton socket instance.
 * Handler registration is delegated to socket-handlers/ modules.
 * Action functions (emit events) are in socketActions.ts.
 */
import { io, Socket } from 'socket.io-client'
import { getSessionId } from './client'
import { useUIStore } from '../stores/uiStore'
import { registerAllHandlers } from './socket-handlers'

let socket: Socket | null = null

/** Get socket server URL — uses Vite proxy in dev, env var in production */
function getSocketUrl(): string {
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL
  }
  // In development with Vite proxy, connect to same origin
  return window.location.origin
}

/** Get the current socket instance (may be null if not connected) */
export function getSocket(): Socket | null {
  return socket
}

/**
 * Create and connect the socket, registering all event handlers.
 * Returns existing socket if already connected (idempotent).
 */
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

  // Connection lifecycle events
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

  // Register all domain-specific event handlers
  registerAllHandlers(socket)

  return socket
}

/** Disconnect and dispose the socket */
export function disconnectSocket(): void {
  if (socket) {
    socket.disconnect()
    socket = null
  }
}

// Re-export all action functions so existing imports from '../api/socket' still work
export {
  sendChatMessage,
  cancelChatTask,
  syncWorkflow,
  startWorkflowExecution,
  pauseWorkflowExecution,
  resumeWorkflowExecution,
  stopWorkflowExecution,
} from './socketActions'
