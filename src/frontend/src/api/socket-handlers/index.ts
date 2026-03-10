/**
 * Socket.IO event handler registration.
 * Delegates to domain-specific handler modules for clean separation of concerns.
 *
 * Each handler module registers its listeners directly on the Socket instance
 * using socket.on('event_name', callback).
 */
import type { Socket } from 'socket.io-client'
import { registerChatHandlers } from './chatHandlers'
import { registerAgentHandlers } from './agentHandlers'
import { registerWorkflowHandlers } from './workflowHandlers'
import { registerExecutionHandlers } from './executionHandlers'

/** Register all domain-specific event handlers on the Socket.IO client */
export function registerAllHandlers(socket: Socket): void {
  registerChatHandlers(socket)
  registerAgentHandlers(socket)
  registerWorkflowHandlers(socket)
  registerExecutionHandlers(socket)
}
