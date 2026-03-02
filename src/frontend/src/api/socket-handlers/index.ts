/**
 * Socket handler registration barrel.
 * Delegates to domain-specific handler modules for clean separation of concerns.
 */
import type { Socket } from 'socket.io-client'
import { registerChatHandlers } from './chatHandlers'
import { registerAgentHandlers } from './agentHandlers'
import { registerWorkflowHandlers } from './workflowHandlers'
import { registerExecutionHandlers } from './executionHandlers'

/** Register all socket event handlers by delegating to domain-specific modules */
export function registerAllHandlers(socket: Socket): void {
  registerChatHandlers(socket)
  registerAgentHandlers(socket)
  registerWorkflowHandlers(socket)
  registerExecutionHandlers(socket)
}
