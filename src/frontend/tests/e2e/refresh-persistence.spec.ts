/**
 * E2E tests for page refresh persistence.
 *
 * Verifies that:
 * - Rich local messages (with tool_calls) survive refresh
 * - Backend messages only replace local when they have genuinely NEW messages
 * - Streaming content is properly handled across refresh boundaries
 * - ConversationId is preserved across refresh
 */
import { test, expect } from '@playwright/test'
import {
  mockAllAPIs, buildChatStorage, seedAndLoad,
  msg, tc, resetMsgCounter,
  type PersistedChatState,
} from './helpers'

const WF_ID = 'wf_e2e_test_00000000000000000000000000'

test.describe('refresh persistence', () => {
  test.beforeEach(async ({ page }) => {
    resetMsgCounter()
    await mockAllAPIs(page)
  })

  test('messages with tool_calls survive page refresh', async ({ page }) => {
    const messages = [
      msg('user', 'build a workflow for patient triage'),
      msg('assistant', 'Done! I created the triage workflow.', [
        tc('add_node', { label: 'Start' }),
        tc('add_node', { label: 'Check vitals' }),
        tc('add_connection', { from: 'n1', to: 'n2' }),
      ]),
    ]

    await seedAndLoad(page, WF_ID, buildChatStorage(WF_ID, messages))

    await expect(page.locator('.message.user')).toHaveCount(1)
    await expect(page.locator('.message.assistant')).toHaveCount(1)
    await expect(page.locator('.message.assistant .tool-call')).toHaveCount(3)
    const toolNames = await page.locator('.message.assistant .tool-name').allTextContents()
    expect(toolNames).toEqual(['add_node', 'add_node', 'add_connection'])

    await page.reload()

    await expect(page.locator('.message.user')).toHaveCount(1)
    await expect(page.locator('.message.assistant')).toHaveCount(1)
    await expect(page.locator('.message.assistant .tool-call')).toHaveCount(3)
    const toolNamesAfter = await page.locator('.message.assistant .tool-name').allTextContents()
    expect(toolNamesAfter).toEqual(['add_node', 'add_node', 'add_connection'])
  })

  test('collapsed tool disclosure (>3 tools) survives refresh', async ({ page }) => {
    const messages = [
      msg('user', 'build it'),
      msg('assistant', 'Created a complex workflow.', [
        tc('add_node', { label: 'A' }),
        tc('add_node', { label: 'B' }),
        tc('add_connection', { from: 'n1', to: 'n2' }),
        tc('add_connection', { from: 'n2', to: 'n3' }),
      ]),
    ]

    await seedAndLoad(page, WF_ID, buildChatStorage(WF_ID, messages))

    await expect(page.locator('.tool-call-disclosure')).toHaveCount(1)
    await expect(page.locator('.tool-call-summary')).toContainText('Tools (4)')

    await page.reload()

    await expect(page.locator('.tool-call-disclosure')).toHaveCount(1)
    await expect(page.locator('.tool-call-summary')).toContainText('Tools (4)')
  })

  test('message content text survives refresh', async ({ page }) => {
    const messages = [
      msg('user', 'Hello from E2E test'),
      msg('assistant', 'Assistant response with **markdown**.'),
    ]

    await seedAndLoad(page, WF_ID, buildChatStorage(WF_ID, messages))

    await expect(page.locator('.message.user .message-content')).toContainText('Hello from E2E test')
    await expect(page.locator('.message.assistant .message-content')).toContainText('Assistant response with markdown.')

    await page.reload()

    await expect(page.locator('.message.user .message-content')).toContainText('Hello from E2E test')
    await expect(page.locator('.message.assistant .message-content')).toContainText('Assistant response with markdown.')
  })

  test('conversationId is preserved in localStorage after refresh', async ({ page }) => {
    const convId = 'conv-persist-check-12345'
    await seedAndLoad(page, WF_ID, buildChatStorage(WF_ID, [msg('user', 'test')], convId))

    const storedBefore = await page.evaluate(() => {
      const raw = localStorage.getItem('lemon-chat')
      return raw ? JSON.parse(raw) : null
    })
    expect(storedBefore?.state?.conversations?.[WF_ID]?.conversationId).toBe(convId)

    await page.reload()

    const storedAfter = await page.evaluate((wfId) => {
      const raw = localStorage.getItem('lemon-chat')
      return raw ? JSON.parse(raw)?.state?.conversations?.[wfId]?.conversationId : null
    }, WF_ID)
    expect(storedAfter).toBe(convId)
  })

  test('stale streaming state does NOT show streaming UI', async ({ page }) => {
    const payload: PersistedChatState = {
      state: {
        activeWorkflowId: WF_ID,
        pendingQuestions: [],
        conversations: {
          [WF_ID]: {
            messages: [{ id: 'msg_1', role: 'user', content: 'test', timestamp: '2024-01-01T00:00:00Z', tool_calls: [] }],
            conversationId: 'conv-transient',
            isStreaming: false, streamingContent: '', _inThinkingBlock: false,
            processingStatus: null, currentTaskId: null, contextUsagePct: 42,
          },
        },
      },
      version: 0,
    }

    await seedAndLoad(page, WF_ID, JSON.stringify(payload))
    await expect(page.locator('.message.user')).toHaveCount(1)
    await expect(page.locator('.message.assistant.streaming')).toHaveCount(0)
    await expect(page.locator('.processing-status')).toHaveCount(0)

    await page.reload()
    await expect(page.locator('.message.user')).toHaveCount(1)
    await expect(page.locator('.message.assistant.streaming')).toHaveCount(0)
  })

  test('multiple messages in correct order after refresh', async ({ page }) => {
    const messages = [
      msg('user', 'First user message'),
      msg('assistant', 'First assistant response', [tc('add_node')]),
      msg('user', 'Second user message'),
      msg('assistant', 'Second assistant response', [tc('validate_workflow'), tc('highlight_node')]),
    ]

    await seedAndLoad(page, WF_ID, buildChatStorage(WF_ID, messages))

    await expect(page.locator('.message')).toHaveCount(4)
    const contents = await page.locator('.message .message-content').allTextContents()
    expect(contents[0]).toContain('First user message')
    expect(contents[3]).toContain('Second assistant response')

    const assistantMessages = page.locator('.message.assistant')
    await expect(assistantMessages.nth(0).locator('.tool-call')).toHaveCount(1)
    await expect(assistantMessages.nth(1).locator('.tool-call')).toHaveCount(2)

    await page.reload()

    await expect(page.locator('.message')).toHaveCount(4)
    await expect(assistantMessages.nth(0).locator('.tool-call')).toHaveCount(1)
    await expect(assistantMessages.nth(1).locator('.tool-call')).toHaveCount(2)
  })

  test('backend messages merge into local after refresh (assistant arrived while page closed)', async ({ page }) => {
    // Scenario: user sent a message, then refreshed while the backend was
    // still processing. The orchestrator finished and the backend now has
    // both user + assistant messages. Local only has the user message.
    // After reload, the assistant message from the backend should appear.
    const CONV_ID = 'conv-merge-test'

    // Seed localStorage with ONLY the user message
    await seedAndLoad(page, WF_ID, buildChatStorage(WF_ID, [msg('user', 'build a triage workflow')], CONV_ID))

    // Verify only user message is present
    await expect(page.locator('.message.user')).toHaveCount(1)
    await expect(page.locator('.message.assistant')).toHaveCount(0)

    // Now re-mock APIs so the workflow detail returns a conversation_id
    // and the chat history returns BOTH user + assistant messages
    await mockAllAPIs(page, {
      workflowDetail: {
        id: WF_ID, name: 'Merge Test',
        nodes: [{ id: 'n1', type: 'start', label: 'Start', x: 100, y: 100, color: 'green' }],
        edges: [], variables: [],
        conversation_id: CONV_ID,
      },
      chatMessages: [
        msg('user', 'build a triage workflow'),
        msg('assistant', 'I built the triage workflow with 5 nodes.', [
          tc('add_node', { label: 'Start' }),
          tc('add_node', { label: 'Triage' }),
          tc('add_connection', { from: 'n1', to: 'n2' }),
        ]),
      ],
    })

    await page.reload()

    // After reload, both messages should be visible — the assistant
    // message was merged from the backend conversation history.
    await expect(page.locator('.message.user')).toHaveCount(1)
    await expect(page.locator('.message.assistant')).toHaveCount(1)
    await expect(page.locator('.message.assistant .message-content')).toContainText('triage workflow')
    await expect(page.locator('.message.assistant .tool-call')).toHaveCount(3)
  })

  test('local messages preserved when backend returns empty history', async ({ page }) => {
    // Scenario: backend chat endpoint returns 0 messages (e.g. task still
    // running, or server restarted with empty ConversationLogger).
    // Local messages should be preserved — not wiped out.
    const CONV_ID = 'conv-empty-backend'

    const messages = [
      msg('user', 'analyze this image'),
      msg('assistant', 'I see a flowchart with 3 nodes.', [
        tc('view_image', {}),
        tc('extract_guidance', {}),
      ]),
    ]

    await seedAndLoad(page, WF_ID, buildChatStorage(WF_ID, messages, CONV_ID))

    await expect(page.locator('.message')).toHaveCount(2)

    // Re-mock with conversation_id but empty chat history (backend has 0 messages)
    await mockAllAPIs(page, {
      workflowDetail: {
        id: WF_ID, name: 'Empty Backend Test',
        nodes: [{ id: 'n1', type: 'start', label: 'Start', x: 100, y: 100, color: 'green' }],
        edges: [], variables: [],
        conversation_id: CONV_ID,
      },
      chatMessages: [],
    })

    await page.reload()

    // Local messages should still be present — backend returning empty
    // should NOT wipe out the richer local state.
    await expect(page.locator('.message')).toHaveCount(2)
    await expect(page.locator('.message.user .message-content')).toContainText('analyze this image')
    await expect(page.locator('.message.assistant .tool-call')).toHaveCount(2)
  })

  test('building flag shows streaming UI on refresh', async ({ page }) => {
    // Scenario: user sent a message, the backend is still processing
    // (building=true). After refresh, the UI should show streaming state.
    await seedAndLoad(page, WF_ID, buildChatStorage(WF_ID, [msg('user', 'build it')]))

    // Re-mock with building=true to simulate in-progress task
    await mockAllAPIs(page, {
      workflowDetail: {
        id: WF_ID, name: 'Building Test',
        nodes: [{ id: 'n1', type: 'start', label: 'Start', x: 100, y: 100, color: 'green' }],
        edges: [], variables: [],
        conversation_id: 'conv-building',
        building: true,
      },
    })

    await page.reload()

    // Streaming UI should appear because the backend is still building.
    // The stop button indicates the frontend entered streaming mode.
    await expect(page.locator('#stopBtn')).toBeVisible({ timeout: 5000 })
    await expect(page.locator('#chatInput')).toBeDisabled()
  })

  test('failed tool calls retain failure badge after refresh', async ({ page }) => {
    const messages = [
      msg('user', 'do something'),
      msg('assistant', 'Tried but one tool failed.', [
        tc('add_node', {}, true),
        tc('validate_workflow', {}, false),
      ]),
    ]

    await seedAndLoad(page, WF_ID, buildChatStorage(WF_ID, messages))

    await expect(page.locator('.tool-call.failed')).toHaveCount(1)
    await expect(page.locator('.tool-call.failed .tool-name')).toContainText('validate_workflow')

    await page.reload()

    await expect(page.locator('.tool-call.failed')).toHaveCount(1)
    await expect(page.locator('.tool-call.failed .tool-name')).toContainText('validate_workflow')
  })
})
