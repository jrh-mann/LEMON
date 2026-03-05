/**
 * WebSocket connection management — singleton native WebSocket.
 * Handler registration is delegated to socket-handlers/ modules.
 * Action functions (send messages) are in socketActions.ts.
 *
 * Protocol: All messages are JSON with {type, payload} structure.
 * Auth is cookie-based (lemon_session cookie sent automatically).
 * Reconnection uses conn_id handshake to rebind background threads.
 */
import { useUIStore } from '../stores/uiStore'
import { registerAllHandlers, dispatchEvent } from './socket-handlers'

let ws: WebSocket | null = null
let savedConnId: string | null = null // Server-assigned connection ID for reconnection
let reconnectAttempts = 0
let intentionalClose = false // Prevents reconnect on logout/navigate-away
const MAX_RECONNECT_ATTEMPTS = 5
const RECONNECT_BASE_DELAY = 1000 // 1s, doubles each attempt

// Handler map populated once by registerAllHandlers()
const handlers: Record<string, (payload: any) => void> = {}
let handlersRegistered = false

/** Build WebSocket URL — uses Vite proxy in dev, env var in production */
function getWsUrl(): string {
  if (import.meta.env.VITE_API_URL) {
    return `${import.meta.env.VITE_API_URL.replace(/^http/, 'ws')}/ws`
  }
  // In development with Vite proxy, connect to same origin via ws://
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws`
}

/** Check if the WebSocket is currently connected */
export function isConnected(): boolean {
  return ws !== null && ws.readyState === WebSocket.OPEN
}

/**
 * Send a JSON message to the backend via WebSocket.
 * Silently no-ops if not connected (callers should check isConnected() for user-facing errors).
 */
export function sendMessage(type: string, payload: Record<string, unknown>): void {
  if (!isConnected()) {
    console.warn('[WS] Cannot send — not connected')
    return
  }
  ws!.send(JSON.stringify({ type, payload }))
}

/**
 * Connect the WebSocket, registering all event handlers.
 * Idempotent — returns immediately if already connected.
 */
export function connectSocket(): void {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return
  }

  // Register handler map once
  if (!handlersRegistered) {
    registerAllHandlers(handlers)
    handlersRegistered = true
  }

  intentionalClose = false
  const url = getWsUrl()
  console.log('[WS] Connecting to:', url)
  ws = new WebSocket(url)

  ws.onopen = () => {
    console.log('[WS] Connected')
    reconnectAttempts = 0
    useUIStore.getState().clearError()

    // Reconnection handshake: always try to rebind if we have a saved conn_id.
    // This ensures background builder events still reach us even when idle.
    if (savedConnId) {
      sendMessage('reconnect', { conn_id: savedConnId })
    }
  }

  ws.onclose = (e) => {
    console.log('[WS] Disconnected:', e.code, e.reason)
    ws = null
    if (!intentionalClose) {
      scheduleReconnect()
    }
  }

  ws.onerror = () => {
    console.error('[WS] Connection error')
    useUIStore.getState().setError('Connection error')
  }

  ws.onmessage = (e) => {
    try {
      const { type, payload } = JSON.parse(e.data)

      // Store conn_id from server for reconnection
      if (type === 'connected' || type === 'reconnected') {
        savedConnId = payload.conn_id
        console.log('[WS]', type, '— conn_id:', savedConnId)
      }

      // Dispatch to registered handlers
      dispatchEvent(handlers, type, payload)
    } catch (err) {
      console.error('[WS] Invalid message:', e.data, err)
    }
  }
}

/** Schedule a reconnect attempt with exponential backoff */
function scheduleReconnect(): void {
  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
    useUIStore.getState().setError('Lost connection to server')
    return
  }
  const delay = RECONNECT_BASE_DELAY * Math.pow(2, reconnectAttempts)
  reconnectAttempts++
  console.log(`[WS] Reconnecting in ${delay}ms (attempt ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})`)
  setTimeout(() => connectSocket(), delay)
}

/** Disconnect and dispose the WebSocket (intentional close — no reconnect) */
export function disconnectSocket(): void {
  intentionalClose = true
  reconnectAttempts = 0
  if (ws) {
    ws.close()
    ws = null
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
