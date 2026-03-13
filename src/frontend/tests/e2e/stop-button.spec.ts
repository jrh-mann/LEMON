/**
 * E2E tests for the stop button.
 *
 * Verifies that:
 * - Clicking stop while streaming preserves existing messages
 * - Partial streamed content is finalized into a message
 * - Chat input is re-enabled after stop
 * - Streaming UI disappears after stop
 * - Conversation history survives stop + refresh
 */
import { test, expect } from '@playwright/test'
import {
  mockAllAPIs, seedAndLoad,
  msg, resetMsgCounter,
  type PersistedChatState,
} from './helpers'

const WF_ID = 'wf_e2e_stop_test_000000000000000000'

test.describe('stop button', () => {
  test.beforeEach(async ({ page }) => {
    resetMsgCounter()
    await mockAllAPIs(page)
  })

  test('clicking stop preserves prior messages and re-enables input', async ({ page }) => {
    // Seed with one completed exchange + active streaming state
    const priorMessages = [
      msg('user', 'build a triage workflow'),
      msg('assistant', 'Here is the triage workflow.', [
        tc('add_node', { label: 'Start' }),
        tc('add_node', { label: 'Check vitals' }),
      ]),
    ]

    // Build storage with streaming state active (simulating mid-stream)
    const payload: PersistedChatState = {
      state: {
        activeWorkflowId: WF_ID,
        pendingQuestions: [],
        conversations: {
          [WF_ID]: {
            messages: [
              ...priorMessages,
              // User sent a second message, assistant is streaming
              msg('user', 'now add an output node'),
            ],
            conversationId: 'conv-stop-test',
            isStreaming: true,
            streamingContent: 'I will add an output node to',
            thinkingContent: '',
            processingStatus: 'Building workflow...',
            currentTaskId: 'task_stop_test_1',
            contextUsagePct: 25,
          },
        },
      },
      version: 0,
    }

    await seedAndLoad(page, WF_ID, JSON.stringify(payload))

    // Streaming UI should be visible
    await expect(page.locator('#stopBtn')).toBeVisible({ timeout: 5000 })
    await expect(page.locator('#chatInput')).toBeDisabled()

    // Prior messages should be visible (streaming content renders as an
    // assistant message too, so we expect 2 assistant messages before stop)
    await expect(page.locator('.message.user')).toHaveCount(2)
    await expect(page.locator('.message.assistant')).toHaveCount(2)

    // Click stop
    await page.click('#stopBtn')

    // Streaming UI should disappear
    await expect(page.locator('#stopBtn')).toBeHidden({ timeout: 3000 })
    await expect(page.locator('#chatInput')).toBeEnabled()

    // Prior messages should still be there
    await expect(page.locator('.message.user')).toHaveCount(2)

    // The streamed content is finalized into a permanent assistant message
    const assistantMessages = page.locator('.message.assistant')
    await expect(assistantMessages).toHaveCount(2)
    await expect(assistantMessages.nth(0).locator('.message-content')).toContainText('triage workflow')
    await expect(assistantMessages.nth(0).locator('.tool-call')).toHaveCount(2)

    // The finalized partial message should contain the streamed text
    await expect(assistantMessages.nth(1).locator('.message-content')).toContainText('output node')
  })

  test('stop with no streamed content preserves messages without adding empty one', async ({ page }) => {
    // Streaming just started (thinking phase) — no streamingContent yet
    const payload: PersistedChatState = {
      state: {
        activeWorkflowId: WF_ID,
        pendingQuestions: [],
        conversations: {
          [WF_ID]: {
            messages: [
              msg('user', 'first question'),
              msg('assistant', 'first answer'),
              msg('user', 'second question'),
            ],
            conversationId: 'conv-stop-empty',
            isStreaming: true,
            streamingContent: '',
            thinkingContent: 'Let me think about this...',
            processingStatus: 'Thinking...',
            currentTaskId: 'task_stop_empty_1',
            contextUsagePct: 10,
          },
        },
      },
      version: 0,
    }

    await seedAndLoad(page, WF_ID, JSON.stringify(payload))

    await expect(page.locator('#stopBtn')).toBeVisible({ timeout: 5000 })

    // 2 user messages + 1 assistant + streaming indicator
    await expect(page.locator('.message.user')).toHaveCount(2)
    await expect(page.locator('.message.assistant').first()).toContainText('first answer')

    await page.click('#stopBtn')

    await expect(page.locator('#stopBtn')).toBeHidden({ timeout: 3000 })
    await expect(page.locator('#chatInput')).toBeEnabled()

    // All prior messages preserved
    await expect(page.locator('.message.user')).toHaveCount(2)
    // No empty assistant message added (streamingContent was '')
    await expect(page.locator('.message.assistant')).toHaveCount(1)
  })

  test('messages survive stop then page refresh', async ({ page }) => {
    const payload: PersistedChatState = {
      state: {
        activeWorkflowId: WF_ID,
        pendingQuestions: [],
        conversations: {
          [WF_ID]: {
            messages: [
              msg('user', 'analyze the image'),
              msg('assistant', 'I see a flowchart with decision nodes.', [
                tc('view_image', {}),
                tc('extract_guidance', {}),
              ]),
              msg('user', 'now build it'),
            ],
            conversationId: 'conv-stop-refresh',
            isStreaming: true,
            streamingContent: 'Starting to build the workflow with',
            thinkingContent: '',
            processingStatus: 'Building...',
            currentTaskId: 'task_stop_refresh_1',
            contextUsagePct: 30,
          },
        },
      },
      version: 0,
    }

    await seedAndLoad(page, WF_ID, JSON.stringify(payload))

    await expect(page.locator('#stopBtn')).toBeVisible({ timeout: 5000 })
    await page.click('#stopBtn')
    await expect(page.locator('#stopBtn')).toBeHidden({ timeout: 3000 })

    // Verify state after stop
    const assistantMessages = page.locator('.message.assistant')
    await expect(assistantMessages).toHaveCount(2)
    await expect(assistantMessages.nth(0).locator('.tool-call')).toHaveCount(2)

    // Refresh the page
    await page.reload()

    // All messages should survive the refresh
    await expect(page.locator('.message.user')).toHaveCount(2)
    await expect(assistantMessages).toHaveCount(2)
    await expect(assistantMessages.nth(0).locator('.tool-call')).toHaveCount(2)
    await expect(assistantMessages.nth(0).locator('.message-content')).toContainText('flowchart')

    // Streaming UI should NOT reappear (isStreaming is stripped by partialize)
    await expect(page.locator('#stopBtn')).toBeHidden()
    await expect(page.locator('#chatInput')).toBeEnabled()
  })

  test('tool calls on prior messages are preserved after stop', async ({ page }) => {
    const payload: PersistedChatState = {
      state: {
        activeWorkflowId: WF_ID,
        pendingQuestions: [],
        conversations: {
          [WF_ID]: {
            messages: [
              msg('user', 'build complex workflow'),
              msg('assistant', 'Created the workflow.', [
                tc('add_node', { label: 'Start' }),
                tc('add_node', { label: 'Decision' }),
                tc('add_connection', { from: 'n1', to: 'n2' }),
                tc('add_node', { label: 'Output' }),
                tc('add_connection', { from: 'n2', to: 'n3' }),
              ]),
              msg('user', 'validate it'),
            ],
            conversationId: 'conv-stop-tools',
            isStreaming: true,
            streamingContent: 'Running validation',
            thinkingContent: '',
            processingStatus: 'Validating...',
            currentTaskId: 'task_stop_tools_1',
            contextUsagePct: 50,
          },
        },
      },
      version: 0,
    }

    await seedAndLoad(page, WF_ID, JSON.stringify(payload))

    await expect(page.locator('#stopBtn')).toBeVisible({ timeout: 5000 })
    await page.click('#stopBtn')
    await expect(page.locator('#stopBtn')).toBeHidden({ timeout: 3000 })

    // The first assistant message should retain all 5 tool calls
    // (>3 means it should be in a collapsed disclosure)
    await expect(page.locator('.tool-call-disclosure')).toHaveCount(1)
    await expect(page.locator('.tool-call-summary')).toContainText('Tools (5)')
  })
})
