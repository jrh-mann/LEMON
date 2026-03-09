import { api } from './client'
import type { ChatRequest, ChatResponse, ConversationContext } from '../types'

// Send a chat message via REST (alternative to socket)
export async function sendChatMessageREST(
  request: ChatRequest
): Promise<ChatResponse> {
  return api.post<ChatResponse>('/api/chat', request)
}

// Get conversation history
export async function getConversation(
  conversationId: string
): Promise<ConversationContext> {
  return api.get<ConversationContext>(`/api/chat/${conversationId}`)
}
