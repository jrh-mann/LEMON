import { describe, it, expect, beforeEach } from 'vitest'
import { useChatStore } from '../../src/stores/chatStore'

// Reset store state between tests
beforeEach(() => {
  useChatStore.getState().reset()
})

describe('chatStore', () => {
  describe('conversations', () => {
    it('creates a conversation entry on first addMessage', () => {
      useChatStore.getState().addMessage('wf_1', {
        id: 'msg_1', role: 'user', content: 'hello',
        timestamp: '2024-01-01T00:00:00Z', tool_calls: [],
      })
      const conv = useChatStore.getState().conversations['wf_1']
      expect(conv).toBeDefined()
      expect(conv.messages).toHaveLength(1)
      expect(conv.messages[0].content).toBe('hello')
    })

    it('keeps separate conversations per workflow', () => {
      const store = useChatStore.getState()
      store.addMessage('wf_1', {
        id: 'msg_1', role: 'user', content: 'wf1 msg',
        timestamp: '2024-01-01T00:00:00Z', tool_calls: [],
      })
      store.addMessage('wf_2', {
        id: 'msg_2', role: 'user', content: 'wf2 msg',
        timestamp: '2024-01-01T00:00:00Z', tool_calls: [],
      })
      expect(useChatStore.getState().conversations['wf_1'].messages[0].content).toBe('wf1 msg')
      expect(useChatStore.getState().conversations['wf_2'].messages[0].content).toBe('wf2 msg')
    })
  })

  describe('conversationId', () => {
    it('setConversationId stores per-workflow', () => {
      const store = useChatStore.getState()
      store.setConversationId('wf_1', 'conv-abc')
      expect(useChatStore.getState().conversations['wf_1'].conversationId).toBe('conv-abc')
    })

    it('ensureConversationId generates UUID if missing', () => {
      const store = useChatStore.getState()
      const id = store.ensureConversationId('wf_1')
      expect(id).toBeTruthy()
      expect(typeof id).toBe('string')
      // Should be a valid UUID format
      expect(id).toMatch(/^[0-9a-f-]{36}$/)
    })

    it('ensureConversationId returns existing ID if already set', () => {
      const store = useChatStore.getState()
      store.setConversationId('wf_1', 'existing-id')
      const id = store.ensureConversationId('wf_1')
      expect(id).toBe('existing-id')
    })
  })

  describe('streaming', () => {
    it('appendStreamContent accumulates text', () => {
      const store = useChatStore.getState()
      store.appendStreamContent('wf_1', 'Hello ')
      store.appendStreamContent('wf_1', 'world')
      expect(useChatStore.getState().conversations['wf_1'].streamingContent).toBe('Hello world')
    })

    it('finalizeStream converts streaming content to message', () => {
      const store = useChatStore.getState()
      store.setStreaming('wf_1', true)
      store.appendStreamContent('wf_1', 'Final answer')
      store.finalizeStream('wf_1', [])
      const conv = useChatStore.getState().conversations['wf_1']
      expect(conv.isStreaming).toBe(false)
      expect(conv.streamingContent).toBe('')
      expect(conv.messages).toHaveLength(1)
      expect(conv.messages[0].content).toBe('Final answer')
      expect(conv.messages[0].role).toBe('assistant')
    })

    it('finalizeStream with no content just clears streaming state', () => {
      const store = useChatStore.getState()
      store.setStreaming('wf_1', true)
      store.finalizeStream('wf_1')
      const conv = useChatStore.getState().conversations['wf_1']
      expect(conv.isStreaming).toBe(false)
      expect(conv.messages).toHaveLength(0)
    })
  })

  describe('task cancellation', () => {
    it('markTaskCancelled makes isTaskCancelled return true', () => {
      const store = useChatStore.getState()
      store.markTaskCancelled('task_123')
      expect(store.isTaskCancelled('task_123')).toBe(true)
    })

    it('unknown task is not cancelled', () => {
      const store = useChatStore.getState()
      expect(store.isTaskCancelled('unknown_task')).toBe(false)
    })
  })

  describe('thinking content', () => {
    it('appendThinkingInline opens a thinking marker and sets _inThinkingBlock', () => {
      const store = useChatStore.getState()
      store.appendThinkingInline('wf_1', 'Let me ')
      let conv = useChatStore.getState().conversations['wf_1']
      expect(conv.streamingContent).toBe('<!--THINKING_START-->Let me ')
      expect(conv._inThinkingBlock).toBe(true)

      // Subsequent chunks accumulate inside the open block
      store.appendThinkingInline('wf_1', 'think...')
      conv = useChatStore.getState().conversations['wf_1']
      expect(conv.streamingContent).toBe('<!--THINKING_START-->Let me think...')
      expect(conv._inThinkingBlock).toBe(true)
    })

    it('appendStreamContent closes the open thinking block before appending', () => {
      const store = useChatStore.getState()
      store.appendThinkingInline('wf_1', 'Let me think...')
      store.appendStreamContent('wf_1', 'Hello')
      const conv = useChatStore.getState().conversations['wf_1']
      expect(conv.streamingContent).toBe('<!--THINKING_START-->Let me think...<!--THINKING_END-->Hello')
      expect(conv._inThinkingBlock).toBe(false)
    })

    it('finalizeStream closes an open thinking block in the final message content', () => {
      const store = useChatStore.getState()
      store.setStreaming('wf_1', true)
      store.appendThinkingInline('wf_1', 'Still thinking...')
      store.finalizeStream('wf_1', [])
      const conv = useChatStore.getState().conversations['wf_1']
      expect(conv.isStreaming).toBe(false)
      expect(conv._inThinkingBlock).toBe(false)
      expect(conv.messages[0].content).toBe('<!--THINKING_START-->Still thinking...<!--THINKING_END-->')
    })
  })

  describe('clearConversation', () => {
    it('removes the conversation entry', () => {
      const store = useChatStore.getState()
      store.addMessage('wf_1', {
        id: 'msg_1', role: 'user', content: 'test',
        timestamp: '2024-01-01T00:00:00Z', tool_calls: [],
      })
      store.clearConversation('wf_1')
      expect(useChatStore.getState().conversations['wf_1']).toBeUndefined()
    })
  })
})
