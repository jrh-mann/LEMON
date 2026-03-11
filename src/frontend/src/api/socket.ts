/**
 * Socket.IO connection management -- singleton socket.io-client instance.
 * Handler registration is delegated to socket-handlers/ modules.
 * Action functions (send messages) are in socketActions.ts.
 *
 * Auth is cookie-based (lemon_session cookie sent automatically by
 * the browser for same-origin connections, handled by the Vite proxy
 * in dev and same-origin in production).
 *
 * Reconnection is handled natively by socket.io-client. The resume_task
 * mechanism (re-routing backend events after page refresh) is triggered
 * from the WorkflowPage component, not from the socket layer.
 */
import { io, type Socket } from 'socket.io-client'
import { useUIStore } from '../stores/uiStore'
import { registerAllHandlers } from './socket-handlers'

let socket: Socket | null = null

/** Build Socket.IO URL -- uses Vite proxy in dev, env var in production */
function getSocketUrl(): string {
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL as string
  }
  // In development with Vite proxy, connect to same origin.
  // The proxy forwards /socket.io/ to the backend.
  return ''
}

/** Check if the Socket.IO client is currently connected */
export function isConnected(): boolean {
  return socket !== null && socket.connected
}

/** Return the current socket session ID, or null if not connected. */
export function getSocketId(): string | null {
  return socket?.id ?? null
}

/**
 * Send an event to the backend via Socket.IO.
 * Silently no-ops if not connected (callers should check isConnected() for user-facing errors).
 */
export function sendMessage(event: string, data: Record<string, unknown>): void {
  if (!isConnected()) {
    console.warn('[SIO] Cannot send -- not connected')
    return
  }
  socket!.emit(event, data)
}

/**
 * Connect the Socket.IO client, registering all event handlers.
 * Idempotent -- returns immediately if already connected.
 *
 * Handles Vite HMR gracefully: when HMR replaces this module, the module-level
 * `socket` variable resets to null but the old Socket instance (from the previous
 * module) may still be alive with its event handlers. We can't reach the old
 * instance to clean it up, so the chat_response handler uses a deduplication
 * guard (_processedResponses in chatHandlers.ts) to prevent duplicate messages.
 */
export function connectSocket(): void {
  if (socket && socket.connected) {
    return
  }

  // Disconnect any stale instance before creating a new one
  if (socket) {
    socket.removeAllListeners()
    socket.disconnect()
    socket = null
  }

  const url = getSocketUrl()
  console.log('[SIO] Connecting to:', url || '(same origin)')

  socket = io(url, {
    // Reconnection is handled natively by socket.io-client
    reconnection: true,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 5000,
    reconnectionAttempts: 5,
    // Cookies are sent automatically for same-origin connections
    withCredentials: true,
  })

  socket.on('connect', () => {
    console.log('[SIO] Connected, id:', socket?.id)
    useUIStore.getState().clearError()
  })

  socket.on('disconnect', (reason) => {
    console.log('[SIO] Disconnected:', reason)
  })

  socket.on('connect_error', (err) => {
    console.error('[SIO] Connection error:', err.message)
    useUIStore.getState().setError('Connection error')
  })

  // Register all domain-specific event handlers directly on the socket
  registerAllHandlers(socket)
}

/**
 * Wait for the socket to be connected. Resolves immediately if already
 * connected, otherwise waits for the 'connect' event (up to timeoutMs).
 * Used by WorkflowPage to ensure resume_task fires after the handshake.
 */
export function waitForConnection(timeoutMs = 5000): Promise<void> {
  if (isConnected()) return Promise.resolve()
  if (!socket) return Promise.reject(new Error('Socket not initialized'))
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      socket?.off('connect', onConnect)
      reject(new Error('Socket connection timeout'))
    }, timeoutMs)
    const onConnect = () => {
      clearTimeout(timer)
      resolve()
    }
    socket!.once('connect', onConnect)
  })
}

/** Disconnect and dispose the Socket.IO client (intentional close -- no reconnect) */
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
  resumeTask,
  startWorkflowExecution,
  pauseWorkflowExecution,
  resumeWorkflowExecution,
  stopWorkflowExecution,
} from './socketActions'
