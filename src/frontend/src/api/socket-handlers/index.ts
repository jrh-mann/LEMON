/**
 * WebSocket event handler registration and dispatch.
 * Delegates to domain-specific handler modules for clean separation of concerns.
 *
 * Each handler module populates a shared handlers map: event_name → callback.
 * dispatchEvent() routes incoming WebSocket messages to the right callback.
 */
import { registerChatHandlers } from './chatHandlers'
import { registerAgentHandlers } from './agentHandlers'
import { registerWorkflowHandlers } from './workflowHandlers'
import { registerExecutionHandlers } from './executionHandlers'

/** Handler map type: event type string → callback */
export type HandlerMap = Record<string, (payload: any) => void>

/** Register all domain-specific event handlers into the handler map */
export function registerAllHandlers(handlers: HandlerMap): void {
  registerChatHandlers(handlers)
  registerAgentHandlers(handlers)
  registerWorkflowHandlers(handlers)
  registerExecutionHandlers(handlers)
}

/** Dispatch an incoming WebSocket event to its registered handler.
 *  Wrapped in try-catch so a single handler failure never kills the WebSocket listener. */
export function dispatchEvent(handlers: HandlerMap, type: string, payload: unknown): void {
  const handler = handlers[type]
  if (!handler) {
    console.warn(`[WS] No handler for event: ${type}`)
    return
  }
  try {
    handler(payload)
  } catch (err) {
    console.error(`[WS] Handler error for "${type}":`, err)
    // Don't re-throw — keep the WebSocket alive
  }
}
