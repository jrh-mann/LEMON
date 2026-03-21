/**
 * E2E tests for the chat input area — textarea, send/stop buttons,
 * empty state suggestions, context meter, and pending files indicator.
 */
import { test, expect } from '@playwright/test'
import {
  mockAllAPIs, buildChatStorage, seedAndLoad,
  msg, resetMsgCounter,
  type PersistedChatState,
} from './helpers'

const WF_ID = 'wf_chatinput_000000000000000000000000'

test.describe('chat input area', () => {
  test.beforeEach(async ({ page }) => {
    resetMsgCounter()
    await mockAllAPIs(page)
  })

  test('chat input textarea is present and enabled when not streaming', async ({ page }) => {
    await seedAndLoad(page, WF_ID, buildChatStorage(WF_ID, [msg('user', 'hello')]))

    const textarea = page.locator('#chatInput')
    await expect(textarea).toBeVisible()
    await expect(textarea).toBeEnabled()
    await expect(textarea).toHaveAttribute('placeholder', /Describe your workflow/)
  })

  test('send button is visible and disabled when input is empty', async ({ page }) => {
    await seedAndLoad(page, WF_ID, buildChatStorage(WF_ID, [msg('user', 'hello')]))

    const sendBtn = page.locator('#sendBtn')
    await expect(sendBtn).toBeVisible()
    await expect(sendBtn).toBeDisabled()
  })

  test('send button becomes enabled when text is typed', async ({ page }) => {
    await seedAndLoad(page, WF_ID, buildChatStorage(WF_ID, [msg('user', 'hello')]))

    await page.locator('#chatInput').fill('Build a workflow')
    const sendBtn = page.locator('#sendBtn')
    await expect(sendBtn).toBeEnabled()
  })

  test('stop button appears when streaming is active', async ({ page }) => {
    // Seed with streaming state active
    const payload: PersistedChatState = {
      state: {
        activeWorkflowId: WF_ID,
        pendingQuestions: [],
        conversations: {
          [WF_ID]: {
            messages: [{ id: 'msg_1', role: 'user', content: 'build it', timestamp: '2024-01-01T00:00:00Z', tool_calls: [] }],
            conversationId: 'conv-1',
            isStreaming: true,
            streamingContent: 'Working on it...',
            _inThinkingBlock: false,
            processingStatus: 'Building workflow...',
            currentTaskId: 'task_123',
            contextUsagePct: 0,
          },
        },
      },
      version: 0,
    }

    await seedAndLoad(page, WF_ID, JSON.stringify(payload))

    // Stop button should be visible instead of send button
    await expect(page.locator('#stopBtn')).toBeVisible()
    await expect(page.locator('#sendBtn')).toHaveCount(0)

    // Input should be disabled during streaming
    await expect(page.locator('#chatInput')).toBeDisabled()
  })

  test('streaming message shows processing status', async ({ page }) => {
    const payload: PersistedChatState = {
      state: {
        activeWorkflowId: WF_ID,
        pendingQuestions: [],
        conversations: {
          [WF_ID]: {
            messages: [],
            conversationId: 'conv-1',
            isStreaming: true,
            streamingContent: '',
            _inThinkingBlock: false,
            processingStatus: 'Analyzing image...',
            currentTaskId: 'task_456',
            contextUsagePct: 0,
          },
        },
      },
      version: 0,
    }

    await seedAndLoad(page, WF_ID, JSON.stringify(payload))

    await expect(page.locator('.processing-status')).toContainText('Analyzing image...')
    await expect(page.locator('.status-dot')).toBeVisible()
  })

  test('streaming message shows thinking content as dropdown', async ({ page }) => {
    // Completed thinking blocks render as collapsed <details> dropdowns
    const payload: PersistedChatState = {
      state: {
        activeWorkflowId: WF_ID,
        pendingQuestions: [],
        conversations: {
          [WF_ID]: {
            messages: [],
            conversationId: 'conv-1',
            isStreaming: true,
            streamingContent: '<!--THINKING_START-->Let me analyze the image carefully...<!--THINKING_END-->Building the workflow now.',
            _inThinkingBlock: false,
            processingStatus: null,
            currentTaskId: 'task_789',
            contextUsagePct: 0,
          },
        },
      },
      version: 0,
    }

    await seedAndLoad(page, WF_ID, JSON.stringify(payload))

    // Completed reasoning renders as a collapsed dropdown
    await expect(page.locator('.message.assistant.streaming')).toBeVisible()
    await expect(page.locator('.reasoning-dropdown')).toBeVisible()
    await expect(page.locator('.reasoning-summary')).toContainText('Reasoning')
  })

  test('empty chat shows suggestions', async ({ page }) => {
    // Seed with empty messages — should show the empty state.
    // Need a real workflow ID so the workspace reveals (not the home screen).
    await mockAllAPIs(page, {
      workflowDetail: {
        id: WF_ID, name: 'Empty Chat Test',
        nodes: [{ id: 'n1', type: 'start', label: 'Start', x: 100, y: 100, color: 'green' }],
        edges: [], variables: [],
      },
    })
    await seedAndLoad(page, WF_ID, buildChatStorage(WF_ID, []))

    // Wait for the chat dock to be visible in the workspace
    await expect(page.locator('.chat-dock')).toBeVisible()
    await expect(page.locator('.chat-empty')).toBeVisible()
    const chipCount = await page.locator('.suggestion-chip').count()
    expect(chipCount).toBeGreaterThanOrEqual(1)
  })

  test('context meter shows usage percentage', async ({ page }) => {
    const payload: PersistedChatState = {
      state: {
        activeWorkflowId: WF_ID,
        pendingQuestions: [],
        conversations: {
          [WF_ID]: {
            messages: [{ id: 'msg_1', role: 'user', content: 'test', timestamp: '2024-01-01T00:00:00Z', tool_calls: [] }],
            conversationId: 'conv-1',
            isStreaming: false,
            streamingContent: '',
            _inThinkingBlock: false,
            processingStatus: null,
            currentTaskId: null,
            contextUsagePct: 65,
          },
        },
      },
      version: 0,
    }

    await seedAndLoad(page, WF_ID, JSON.stringify(payload))

    // Context meter should be visible when usage > 0
    await expect(page.locator('.context-meter')).toBeVisible()
    await expect(page.locator('.context-label')).toContainText('65%')
  })

  test('context meter shows warning state at high usage', async ({ page }) => {
    const payload: PersistedChatState = {
      state: {
        activeWorkflowId: WF_ID,
        pendingQuestions: [],
        conversations: {
          [WF_ID]: {
            messages: [{ id: 'msg_1', role: 'user', content: 'test', timestamp: '2024-01-01T00:00:00Z', tool_calls: [] }],
            conversationId: 'conv-1',
            isStreaming: false,
            streamingContent: '',
            _inThinkingBlock: false,
            processingStatus: null,
            currentTaskId: null,
            contextUsagePct: 85,
          },
        },
      },
      version: 0,
    }

    await seedAndLoad(page, WF_ID, JSON.stringify(payload))

    await expect(page.locator('.context-fill.warn')).toBeVisible()
  })
})
