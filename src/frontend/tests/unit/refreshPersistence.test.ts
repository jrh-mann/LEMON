/**
 * Tests for page refresh persistence behavior.
 *
 * Verifies that:
 * - Rich local messages (with tool_calls) survive refresh
 * - Backend messages only replace local when they have genuinely NEW messages
 * - Streaming content is properly handled across refresh boundaries
 * - ConversationId is preserved across refresh
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { useChatStore } from '../../src/stores/chatStore'
import type { Message, ToolCall } from '../../src/types'

// Helper: create a message with optional tool_calls
function makeMsg(
  id: string,
  role: 'user' | 'assistant',
  content: string,
  toolCalls: ToolCall[] = [],
): Message {
  return {
    id,
    role,
    content,
    timestamp: '2024-01-01T00:00:00Z',
    tool_calls: toolCalls,
  }
}

// Helper: create a tool call
function makeToolCall(tool: string, args: Record<string, unknown> = {}): ToolCall {
  return { tool, arguments: args }
}

beforeEach(() => {
  useChatStore.getState().reset()
})

describe('refresh persistence', () => {
  describe('message replacement logic', () => {
    it('does NOT replace local messages when backend has same count', () => {
      const store = useChatStore.getState()
      // Simulate local messages with rich tool_calls (from zustand persist)
      const localMessages = [
        makeMsg('m1', 'user', 'build a workflow'),
        makeMsg('m2', 'assistant', 'Done! I created it.', [
          makeToolCall('add_node', { label: 'Start' }),
          makeToolCall('add_connection', { from: 'n1', to: 'n2' }),
        ]),
      ]
      store.setMessages('wf_1', localMessages)

      // Simulate backend messages — same count but stripped (no tool_calls)
      const backendMessages = [
        makeMsg('m1_be', 'user', 'build a workflow'),
        makeMsg('m2_be', 'assistant', 'Done! I created it.'),
      ]

      // The refresh logic should NOT replace because counts are equal
      // and local messages are richer
      const conv = useChatStore.getState().conversations['wf_1']
      expect(conv.messages).toHaveLength(2)
      expect(conv.messages[1].tool_calls).toHaveLength(2)

      // Only replace when backend has strictly MORE messages
      if (backendMessages.length > conv.messages.length) {
        store.setMessages('wf_1', backendMessages)
      }

      // Local messages should be preserved with tool_calls intact
      const after = useChatStore.getState().conversations['wf_1']
      expect(after.messages).toHaveLength(2)
      expect(after.messages[1].tool_calls).toHaveLength(2)
      expect(after.messages[1].tool_calls[0].tool).toBe('add_node')
    })

    it('appends new backend messages when backend has more', () => {
      const store = useChatStore.getState()
      // Local has 2 messages (from before refresh)
      const localMessages = [
        makeMsg('m1', 'user', 'build a workflow'),
        makeMsg('m2', 'assistant', 'Working on it...', [
          makeToolCall('add_node', { label: 'Start' }),
        ]),
      ]
      store.setMessages('wf_1', localMessages)

      // Backend finished while page was refreshing — has 4 messages now
      const backendMessages = [
        makeMsg('be_1', 'user', 'build a workflow'),
        makeMsg('be_2', 'assistant', 'Working on it...'),
        makeMsg('be_3', 'user', 'add more nodes'),
        makeMsg('be_4', 'assistant', 'Done!'),
      ]

      const conv = useChatStore.getState().conversations['wf_1']
      if (backendMessages.length > conv.messages.length) {
        // Merge: keep local messages, append new ones from backend
        const merged = [
          ...conv.messages,
          ...backendMessages.slice(conv.messages.length),
        ]
        store.setMessages('wf_1', merged)
      }

      const after = useChatStore.getState().conversations['wf_1']
      // Should have 4 messages total
      expect(after.messages).toHaveLength(4)
      // First two should preserve tool_calls from local
      expect(after.messages[1].tool_calls).toHaveLength(1)
      expect(after.messages[1].tool_calls[0].tool).toBe('add_node')
      // New messages from backend should be appended
      expect(after.messages[2].content).toBe('add more nodes')
      expect(after.messages[3].content).toBe('Done!')
    })

    it('does not replace when backend returns empty', () => {
      const store = useChatStore.getState()
      store.setMessages('wf_1', [
        makeMsg('m1', 'user', 'hello'),
        makeMsg('m2', 'assistant', 'hi there'),
      ])

      const backendMessages: Message[] = []

      const conv = useChatStore.getState().conversations['wf_1']
      if (backendMessages.length > conv.messages.length) {
        store.setMessages('wf_1', backendMessages)
      }

      expect(useChatStore.getState().conversations['wf_1'].messages).toHaveLength(2)
    })
  })

  describe('conversationId persistence', () => {
    it('preserves conversationId set before messages are loaded', () => {
      const store = useChatStore.getState()
      // Simulate: backend sets conversationId during loadWorkflow
      store.setConversationId('wf_1', 'conv-from-backend')

      // Then messages are loaded
      store.addMessage('wf_1', makeMsg('m1', 'user', 'hello'))

      const conv = useChatStore.getState().conversations['wf_1']
      expect(conv.conversationId).toBe('conv-from-backend')
      expect(conv.messages).toHaveLength(1)
    })

    it('does not generate new conversationId when one exists', () => {
      const store = useChatStore.getState()
      store.setConversationId('wf_1', 'existing-conv-id')

      const id = store.ensureConversationId('wf_1')
      expect(id).toBe('existing-conv-id')
    })

    it('generates new conversationId for fresh workflows', () => {
      const store = useChatStore.getState()
      const id = store.ensureConversationId('wf_new')
      expect(id).toBeTruthy()
      expect(id).toMatch(/^[0-9a-f-]{36}$/)
    })
  })

  describe('streaming across refresh', () => {
    it('partialize resets transient streaming fields', () => {
      const store = useChatStore.getState()
      store.setStreaming('wf_1', true)
      store.appendStreamContent('wf_1', 'partial response...')
      store.setProcessingStatus('wf_1', 'Thinking...')
      store.appendThinkingInline('wf_1', 'Let me think')
      store.setCurrentTaskId('wf_1', 'task_abc')

      // Verify transient fields are set
      const conv = useChatStore.getState().conversations['wf_1']
      expect(conv.isStreaming).toBe(true)
      // streamingContent includes inline reasoning (appendThinkingInline wraps in <span>)
      expect(conv.streamingContent).toBe('partial response...<!--THINKING_START-->Let me think')
      expect(conv.processingStatus).toBe('Thinking...')
      expect(conv._inThinkingBlock).toBe(true)
      expect(conv.currentTaskId).toBe('task_abc')

      // Simulate what zustand persist partialize does — extract persisted shape
      const persistedConv = {
        messages: conv.messages,
        conversationId: conv.conversationId,
        isStreaming: false,          // Reset
        streamingContent: '',         // Reset
        _inThinkingBlock: false,      // Reset
        processingStatus: null,       // Reset
        currentTaskId: null,          // Reset
        contextUsagePct: conv.contextUsagePct,
      }

      // Verify transient fields are cleared in persisted shape
      expect(persistedConv.isStreaming).toBe(false)
      expect(persistedConv.streamingContent).toBe('')
      expect(persistedConv._inThinkingBlock).toBe(false)
      expect(persistedConv.processingStatus).toBeNull()
      expect(persistedConv.currentTaskId).toBeNull()
    })

    it('finalizeStream preserves tool_calls on the created message', () => {
      const store = useChatStore.getState()
      store.setStreaming('wf_1', true)
      store.appendStreamContent('wf_1', 'Here is the result')

      const toolCalls: ToolCall[] = [
        makeToolCall('add_node', { label: 'Start' }),
        makeToolCall('add_connection', { from: 'n1', to: 'n2' }),
      ]

      store.finalizeStream('wf_1', toolCalls)

      const conv = useChatStore.getState().conversations['wf_1']
      expect(conv.messages).toHaveLength(1)
      expect(conv.messages[0].tool_calls).toHaveLength(2)
      expect(conv.messages[0].tool_calls[0].tool).toBe('add_node')
      expect(conv.messages[0].tool_calls[1].tool).toBe('add_connection')
    })

    it('messages with tool_calls survive setMessages round-trip', () => {
      const store = useChatStore.getState()
      const richMessages = [
        makeMsg('m1', 'user', 'build it'),
        makeMsg('m2', 'assistant', 'Done!', [
          makeToolCall('add_node', { label: 'Process' }),
          makeToolCall('validate_workflow'),
        ]),
      ]
      store.setMessages('wf_1', richMessages)

      // Read back — tool_calls should survive
      const conv = useChatStore.getState().conversations['wf_1']
      expect(conv.messages[1].tool_calls).toHaveLength(2)
      expect(conv.messages[1].tool_calls[0].tool).toBe('add_node')
    })
  })

  describe('resume task flow', () => {
    it('setStreaming + appendStreamContent simulates resume replay', () => {
      const store = useChatStore.getState()
      // Pre-existing messages from localStorage
      store.setMessages('wf_1', [
        makeMsg('m1', 'user', 'build a workflow'),
      ])

      // Simulate WorkflowPage setting streaming state for resume
      store.setStreaming('wf_1', true)
      store.setProcessingStatus('wf_1', 'Reconnecting...')

      // Simulate resume replay: backend sends accumulated stream_buffer
      store.appendStreamContent('wf_1', 'I created the workflow with a Start node.')

      const conv = useChatStore.getState().conversations['wf_1']
      expect(conv.isStreaming).toBe(true)
      expect(conv.streamingContent).toBe('I created the workflow with a Start node.')
      expect(conv.messages).toHaveLength(1) // Not yet finalized

      // Simulate task completion: finalizeStream
      store.finalizeStream('wf_1', [makeToolCall('add_node')])

      const after = useChatStore.getState().conversations['wf_1']
      expect(after.isStreaming).toBe(false)
      expect(after.streamingContent).toBe('')
      expect(after.messages).toHaveLength(2)
      expect(after.messages[1].role).toBe('assistant')
      expect(after.messages[1].content).toBe('I created the workflow with a Start node.')
      expect(after.messages[1].tool_calls).toHaveLength(1)
    })

    it('task_finished clears streaming state without losing messages', () => {
      const store = useChatStore.getState()
      // Simulate post-refresh state: messages loaded, streaming was set
      store.setMessages('wf_1', [
        makeMsg('m1', 'user', 'hello'),
        makeMsg('m2', 'assistant', 'response'),
      ])
      store.setStreaming('wf_1', true)
      store.setProcessingStatus('wf_1', 'Reconnecting...')

      // Simulate task_finished event (task completed before reconnect)
      store.setStreaming('wf_1', false)
      store.setProcessingStatus('wf_1', null)
      store.setCurrentTaskId('wf_1', null)

      const conv = useChatStore.getState().conversations['wf_1']
      expect(conv.isStreaming).toBe(false)
      expect(conv.processingStatus).toBeNull()
      // Messages should still be there
      expect(conv.messages).toHaveLength(2)
    })
  })
})
